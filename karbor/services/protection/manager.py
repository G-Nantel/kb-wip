# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Protection Service
"""

from datetime import datetime
import six

from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging

from karbor.common import constants
from karbor import exception
from karbor.i18n import _, _LI, _LE
from karbor import manager
from karbor.resource import Resource
from karbor.services.protection.flows import worker as flow_manager
from karbor.services.protection.protectable_registry import ProtectableRegistry
from karbor.services.protection.provider import PluggableProtectionProvider
from karbor import utils

LOG = logging.getLogger(__name__)

protection_manager_opts = [
    cfg.StrOpt('provider_registry',
               default='karbor.services.protection.provider.ProviderRegistry',
               help='the provider registry')
]

CONF = cfg.CONF
CONF.register_opts(protection_manager_opts)

PROVIDER_NAMESPACE = 'karbor.provider'


class ProtectionManager(manager.Manager):
    """karbor Protection Manager."""

    RPC_API_VERSION = '1.0'

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, service_name=None,
                 *args, **kwargs):
        super(ProtectionManager, self).__init__(*args, **kwargs)
        provider_reg = CONF.provider_registry
        self.provider_registry = utils.load_plugin(PROVIDER_NAMESPACE,
                                                   provider_reg)
        self.protectable_registry = ProtectableRegistry()
        self.protectable_registry.load_plugins()
        self.worker = flow_manager.Worker()

    def init_host(self, **kwargs):
        """Handle initialization if this is a standalone service"""
        # TODO(wangliuan)
        LOG.info(_LI("Starting protection service"))

    @messaging.expected_exceptions(exception.InvalidPlan,
                                   exception.ProviderNotFound,
                                   exception.FlowError)
    def protect(self, context, plan):
        """create protection for the given plan

        :param plan: Define that protection plan should be done
        """

        LOG.info(_LI("Starting protection service:protect action"))
        LOG.debug("protecting: %s type: %s", plan, type(plan))

        if not plan:
            raise exception.InvalidPlan(
                reason=_('the protection plan is None'))
        provider_id = plan.get('provider_id', None)
        plan_id = plan.get('id', None)
        provider = self.provider_registry.show_provider(provider_id)
        if not provider:
            raise exception.ProviderNotFound(provider_id=provider_id)
        try:
            protection_flow = self.worker.get_flow(context,
                                                   constants.OPERATION_PROTECT,
                                                   plan=plan,
                                                   provider=provider)
        except Exception:
            LOG.exception(_LE("Failed to create protection flow, plan: %s"),
                          plan_id)
            raise exception.FlowError(
                flow="protect",
                error=_("Failed to create flow"))
        try:
            self.worker.run_flow(protection_flow)
        except Exception:
            LOG.exception(_LE("Failed to run protection flow, plan: %s"),
                          plan_id)

            raise exception.FlowError(
                flow="protect",
                error=_("Failed to run flow"))
        finally:
            checkpoint = self.worker.flow_outputs(protection_flow,
                                                  target='checkpoint')
            return {'checkpoint_id': checkpoint.id}

    @messaging.expected_exceptions(exception.InvalidInput,
                                   exception.CheckpointNotAvailable,
                                   exception.FlowError)
    def restore(self, context, restore=None):
        LOG.info(_LI("Starting restore service:restore action"))

        checkpoint_id = restore["checkpoint_id"]
        provider_id = restore["provider_id"]
        provider = self.provider_registry.show_provider(provider_id)
        try:
            checkpoint_collection = provider.get_checkpoint_collection()
            checkpoint = checkpoint_collection.get(checkpoint_id)
        except Exception:
            LOG.error(_LE("Invalid checkpoint id: %s"), checkpoint_id)
            raise exception.InvalidInput(
                reason=_("Invalid checkpoint id"))

        if checkpoint.status in [constants.CHECKPOINT_STATUS_ERROR,
                                 constants.CHECKPOINT_STATUS_PROTECTING]:
            raise exception.CheckpointNotAvailable(
                checkpoint_id=checkpoint_id)

        try:
            restoration_flow = self.worker.get_restoration_flow(
                context,
                constants.OPERATION_RESTORE,
                checkpoint,
                provider,
                restore)
        except Exception:
            LOG.exception(
                _LE("Failed to create restoration flow checkpoint: %s"),
                checkpoint_id)
            raise exception.FlowError(
                flow="restore",
                error=_("Failed to create flow"))
        try:
            self.worker.run_flow(restoration_flow)
            return True
        except Exception:
            LOG.exception(
                _LE("Failed to run restoration flow checkpoint: %s"),
                checkpoint_id)
            raise exception.FlowError(
                flow="restore",
                error=_("Failed to run flow"))

    def delete(self, context, provider_id, checkpoint_id):
        LOG.info(_LI("Starting protection service:delete action"))
        LOG.debug('provider_id :%s checkpoint_id:%s', provider_id,
                  checkpoint_id)
        provider = self.provider_registry.show_provider(provider_id)
        try:
            checkpoint_collection = provider.get_checkpoint_collection()
            checkpoint = checkpoint_collection.get(checkpoint_id)
        except Exception:
            LOG.error(_LE("get checkpoint failed, checkpoint_id:%s"),
                      checkpoint_id)
            raise exception.InvalidInput(
                reason=_("Invalid checkpoint_id or provider_id"))

        if checkpoint.status in [
            constants.CHECKPOINT_STATUS_ERROR,
            constants.CHECKPOINT_STATUS_PROTECTING
        ]:
            raise exception.CheckpointNotBeDeleted(
                checkpoint_id=checkpoint_id)
        checkpoint.status = constants.CHECKPOINT_STATUS_DELETING
        checkpoint.commit()

        try:
            delete_checkpoint_flow = self.worker.get_delete_checkpoint_flow(
                context,
                constants.OPERATION_DELETE,
                checkpoint,
                provider)
        except Exception:
            LOG.exception(
                _LE("Failed to create delete checkpoint flow, checkpoint:%s."),
                checkpoint_id)
            raise exception.KarborException(_(
                "Failed to create delete checkpoint flow."
            ))
        try:
            self.worker.run_flow(delete_checkpoint_flow)
            return True
        except Exception:
            LOG.exception(_LE("Failed to run delete checkpoint flow"))
            raise

    def start(self, plan):
        # TODO(wangliuan)
        pass

    def suspend(self, plan):
        # TODO(wangliuan)
        pass

    @messaging.expected_exceptions(exception.ProviderNotFound,
                                   exception.CheckpointNotFound)
    def list_checkpoints(self, context, provider_id, marker=None, limit=None,
                         sort_keys=None, sort_dirs=None, filters=None):
        LOG.info(_LI("Starting list checkpoints. "
                     "provider_id:%s"), provider_id)
        plan_id = filters.get("plan_id", None)
        start_date = None
        end_date = None
        if filters.get("start_date", None):
            start_date = datetime.strptime(
                filters.get("start_date"), "%Y-%m-%d")
        if filters.get("end_date", None):
            end_date = datetime.strptime(
                filters.get("end_date"), "%Y-%m-%d")
        sort_dir = None if sort_dirs is None else sort_dirs[0]
        provider = self.provider_registry.show_provider(provider_id)
        if provider is None:
            raise exception.ProviderNotFound(provider_id=provider_id)
        checkpoint_ids = provider.list_checkpoints(
            limit=limit, marker=marker, plan_id=plan_id,
            start_date=start_date, end_date=end_date, sort_dir=sort_dir)
        checkpoints = []
        for checkpoint_id in checkpoint_ids:
            checkpoint = provider.get_checkpoint(checkpoint_id)
            checkpoints.append(checkpoint.to_dict())
        return checkpoints

    @messaging.expected_exceptions(exception.ProviderNotFound,
                                   exception.CheckpointNotFound)
    def show_checkpoint(self, context, provider_id, checkpoint_id):
        provider = self.provider_registry.show_provider(provider_id)
        if provider is None:
            raise exception.ProviderNotFound(provider_id=provider_id)

        checkpoint = provider.get_checkpoint(checkpoint_id)
        return checkpoint.to_dict()

    def list_protectable_types(self, context):
        LOG.info(_LI("Start to list protectable types."))
        return self.protectable_registry.list_resource_types()

    @messaging.expected_exceptions(exception.ProtectableTypeNotFound)
    def show_protectable_type(self, context, protectable_type):
        LOG.info(_LI("Start to show protectable type %s"),
                 protectable_type)

        plugin = self.protectable_registry.get_protectable_resource_plugin(
            protectable_type)
        if not plugin:
            raise exception.ProtectableTypeNotFound(
                protectable_type=protectable_type)

        dependents = []
        for t in self.protectable_registry.list_resource_types():
            if t == protectable_type:
                continue

            p = self.protectable_registry.get_protectable_resource_plugin(t)
            if p and protectable_type in p.get_parent_resource_types():
                dependents.append(t)

        return {
            'name': plugin.get_resource_type(),
            "dependent_types": dependents
        }

    @messaging.expected_exceptions(exception.ListProtectableResourceFailed)
    def list_protectable_instances(self, context,
                                   protectable_type=None,
                                   marker=None,
                                   limit=None,
                                   sort_keys=None,
                                   sort_dirs=None,
                                   filters=None):

        LOG.info(_LI("Start to list protectable instances of type: %s"),
                 protectable_type)

        try:
            resource_instances = self.protectable_registry.list_resources(
                context, protectable_type)
        except exception.ListProtectableResourceFailed as err:
            LOG.error(_LE("List resources of type %(type)s failed: %(err)s"),
                      {'type': protectable_type,
                       'err': six.text_type(err)})
            raise

        result = []
        for resource in resource_instances:
            result.append(dict(id=resource.id, name=resource.name))

        return result

    @messaging.expected_exceptions(exception.ListProtectableResourceFailed)
    def show_protectable_instance(self, context, protectable_type,
                                  protectable_id):
        LOG.info(_LI("Start to show protectable instance of type: %s"),
                 protectable_type)

        try:
            resource_instance = \
                self.protectable_registry.show_resource(context,
                                                        protectable_type,
                                                        protectable_id)
        except exception.ListProtectableResourceFailed as err:
            LOG.error(_LE("Show resources of type %(type)s id %(id)s "
                          "failed: %(err)s"),
                      {'type': protectable_type,
                       'id': protectable_id,
                       'err': six.text_type(err)})
            raise

        return dict(id=resource_instance.id, name=resource_instance.name,
                    type=resource_instance.type)

    @messaging.expected_exceptions(exception.ListProtectableResourceFailed)
    def list_protectable_dependents(self, context,
                                    protectable_id,
                                    protectable_type):
        LOG.info(_LI("Start to list dependents of resource "
                     "(type:%(type)s, id:%(id)s)"),
                 {'type': protectable_type,
                  'id': protectable_id})

        parent_resource = Resource(type=protectable_type, id=protectable_id,
                                   name="")

        try:
            dependent_resources = \
                self.protectable_registry.fetch_dependent_resources(
                    context, parent_resource)
        except exception.ListProtectableResourceFailed as err:
            LOG.error(_LE("List dependent resources of (%(res)s) "
                          "failed: %(err)s"),
                      {'res': parent_resource,
                       'err': six.text_type(err)})
            raise

        result = []
        for resource in dependent_resources:
            result.append(dict(type=resource.type, id=resource.id,
                               name=resource.name))

        return result

    def list_providers(self, context, marker=None, limit=None,
                       sort_keys=None, sort_dirs=None, filters=None):
        return self.provider_registry.list_providers(marker=marker,
                                                     limit=limit,
                                                     sort_keys=sort_keys,
                                                     sort_dirs=sort_dirs,
                                                     filters=filters)

    @messaging.expected_exceptions(exception.ProviderNotFound)
    def show_provider(self, context, provider_id):
        provider = self.provider_registry.show_provider(provider_id)
        if isinstance(provider, PluggableProtectionProvider):
            response = {'id': provider.id,
                        'name': provider.name,
                        'description': provider.description,
                        'extended_info_schema': provider.extended_info_schema,
                        }
            return response
        else:
            raise exception.ProviderNotFound(provider_id=provider_id)