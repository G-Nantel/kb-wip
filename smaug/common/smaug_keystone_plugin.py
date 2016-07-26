#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from keystoneauth1 import access
from keystoneauth1.identity import access as access_plugin
from keystoneauth1 import loading
from keystoneauth1 import session as keystone_session
from keystoneclient.v3 import client as kc_v3
from oslo_config import cfg
from oslo_log import log as logging

from smaug import exception
from smaug.i18n import _LW
from smaug import utils


LOG = logging.getLogger(__name__)

CONF = cfg.CONF

# the config of trustee is like:
# [trustee]
# auth_type = password
# auth_url = http://192.168.1.2:35357
# username = smaug
# password = password
# user_domain_id = default
TRUSTEE_CONF_GROUP = 'trustee'
loading.register_auth_conf_options(CONF, TRUSTEE_CONF_GROUP)


class SmaugKeystonePlugin(object):
    """Contruct a keystone client plugin with Smaug user

       to offer the following functions:

       1. get the endpoint of service, such as nova, cinder
       2. create trust to smaug
    """

    def __init__(self):

        self._client = None
        self._auth_uri = ""
        self._smaug_user_id = ""

        self._do_init()

    def _do_init(self):
        auth_plugin = self._get_smaug_auth_plugin()
        # set the project which smaug belongs to
        auth_plugin._project_name = "service"
        auth_plugin._project_domain_id = "default"

        self._client = self._get_keystone_client(auth_plugin)

        lcfg = CONF[TRUSTEE_CONF_GROUP]
        self._smaug_user_id = self._get_service_user(
            lcfg.username, lcfg.user_domain_id)

        try:
            self._auth_uri = utils.get_auth_uri()
        except Exception:
            msg = 'get keystone auth url failed'
            raise exception.AuthorizationFailure(obj=msg)

    def get_service_endpoint(self, service_name, service_type,
                             region_id, interface='public'):
        try:
            service = self._client.services.list(
                name=service_name,
                service_type=service_type,
                base_url=self._auth_uri)

            endpoint = self._client.endpoints.list(
                service=service[0],
                interface=interface,
                region_id=region_id,
                base_url=self._auth_uri)

            return endpoint[0].url if endpoint else None

        except Exception:
            msg = ('get service(%s) endpoint failed' % service_name)
            raise exception.AuthorizationFailure(obj=msg)

    def create_trust_to_smaug(self, context):
        if not context.auth_token_info:
            msg = ("user=%s, project=%s" % (context.user_id,
                                            context.project_id))
            raise exception.AuthorizationFailure(obj=msg)

        auth_ref = access.create(body=context.auth_token_info,
                                 auth_token=context.auth_token)
        user_auth_plugin = access_plugin.AccessInfoPlugin(
            auth_url=self._auth_uri, auth_ref=auth_ref)
        l_kc_v3 = self._get_keystone_client(user_auth_plugin)
        try:
            trust = l_kc_v3.trusts.create(trustor_user=context.user_id,
                                          trustee_user=self._smaug_user_id,
                                          project=context.project_id,
                                          impersonation=True,
                                          role_names=context.roles)
            return trust.id

        except Exception as e:
            raise exception.AuthorizationFailure(obj=str(e))

    def delete_trust_to_smaug(self, trust_id):
        auth_plugin = self._get_smaug_auth_plugin(trust_id)
        client = self._get_keystone_client(auth_plugin)
        client.trusts.delete(trust_id)

    def create_trust_session(self, trust_id):
        auth_plugin = self._get_smaug_auth_plugin(trust_id)
        return keystone_session.Session(auth=auth_plugin)

    def _get_service_user(self, user_name, user_domain_id):
        try:
            users = self._client.users.list(
                name=user_name,
                domain=user_domain_id)

            return users[0].id if users else None

        except Exception:
            msg = ("get service's user(%s) endpoint failed" % user_name)
            raise exception.AuthorizationFailure(obj=msg)

    def _get_smaug_auth_plugin(self, trust_id=None):
        auth_plugin = loading.load_auth_from_conf_options(
            CONF, TRUSTEE_CONF_GROUP, trust_id=trust_id)

        if not auth_plugin:
            LOG.warning(_LW('Please add the trustee credentials you '
                            'need to the %s section of your smaug.conf '
                            'file.') % TRUSTEE_CONF_GROUP)
            raise exception.AuthorizationFailure(obj=TRUSTEE_CONF_GROUP)

        return auth_plugin

    def _get_keystone_client(self, auth_plugin):
        try:
            l_session = keystone_session.Session(auth=auth_plugin)
            return kc_v3.Client(session=l_session)
        except Exception:
            msg = 'create keystone client failed'
            raise exception.AuthorizationFailure(obj=msg)