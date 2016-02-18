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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey
from sqlalchemy import Integer, MetaData, String, Table, Text


def define_tables(meta):

    services = Table(
        'services', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('host', String(length=255)),
        Column('binary', String(length=255)),
        Column('topic', String(length=255)),
        Column('report_count', Integer, nullable=False),
        Column('disabled', Boolean),
        Column('disabled_reason', String(length=255)),
        Column('modified_at', DateTime),
        Column('rpc_current_version', String(36)),
        Column('rpc_available_version', String(36)),
        mysql_engine='InnoDB'
    )

    plans = Table(
        'plans', meta,
        Column('id', String(36), primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('provider_id', String(length=36)),
        Column('project_id', String(length=255)),
        Column('status', String(length=64)),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        mysql_engine='InnoDB'
    )

    resources = Table(
        'resources', meta,
        Column('id', Integer, primary_key=True, nullable=False),
        Column('plan_id', String(length=36), ForeignKey('plans.id'),
               nullable=False),
        Column('resource_id', String(length=36)),
        Column('resource_type', String(length=64)),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        mysql_engine='InnoDB'
    )

    restores = Table(
        'restores', meta,
        Column('id', String(36), primary_key=True, nullable=False),
        Column('project_id', String(length=255)),
        Column('provider_id', String(length=36)),
        Column('checkpoint_id', String(length=36)),
        Column('restore_target', String(length=255)),
        Column('parameters', String(length=255)),
        Column('status', String(length=64)),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        mysql_engine='InnoDB'
    )

    triggers = Table(
        'triggers', meta,
        Column('id', String(36), primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('project_id', String(length=255)),
        Column('type', String(length=64)),
        Column('properties', Text),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        mysql_engine='InnoDB'
    )

    scheduled_operations = Table(
        'scheduled_operations', meta,
        Column('id', String(36), primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('operation_type', String(length=64)),
        Column('project_id', String(length=255)),
        Column('trigger_id', String(length=36)),
        Column('operation_definition', Text),
        Column('status', String(length=64)),
        Column('service_id', String(length=36)),
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        mysql_engine='InnoDB'
    )

    scheduled_operation_logs = Table(
        'scheduled_operation_logs',
        meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False,
               autoincrement=True),
        Column('operation_id', String(length=36),
               ForeignKey('scheduled_operations.id', ondelete='CASCADE'),
               nullable=False),
        Column('expect_start_time', DateTime),
        Column('triggered_time', DateTime),
        Column('actual_start_time', DateTime),
        Column('end_time', DateTime),
        Column('state', String(length=32), nullable=False),
        Column('extend_info', Text),
        mysql_engine='InnoDB'
    )

    return [services,
            plans,
            resources,
            restores,
            triggers,
            scheduled_operations,
            scheduled_operation_logs]


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # create all tables
    # Take care on create order for those with FK dependencies
    tables = define_tables(meta)

    for table in tables:
        table.create()

    if migrate_engine.name == "mysql":
        tables = ["migrate_version",
                  "services"]

        migrate_engine.execute("SET foreign_key_checks = 0")
        for table in tables:
            migrate_engine.execute(
                "ALTER TABLE %s CONVERT TO CHARACTER SET utf8" % table)
        migrate_engine.execute("SET foreign_key_checks = 1")
        migrate_engine.execute(
            "ALTER DATABASE %s DEFAULT CHARACTER SET utf8" %
            migrate_engine.url.database)
        migrate_engine.execute("ALTER TABLE %s Engine=InnoDB" % table)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    tables = define_tables(meta)
    tables.reverse()
    for table in tables:
        table.drop()
