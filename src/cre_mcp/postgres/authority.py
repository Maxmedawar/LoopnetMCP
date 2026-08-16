"""Shared least-privilege preflights for dedicated PostgreSQL login roles."""

from __future__ import annotations

import psycopg

ADMISSION_ROLE = "medawarcre_admission"
ADMISSION_FUNCTIONS = frozenset(
    {
        (
            "atomic_admit_tool_call",
            "uuid, uuid, text, uuid, uuid, text, text, text, text, text[], text, bytea, text, boolean, bytea",
        ),
        (
            "record_tool_call_final",
            "uuid, uuid, text, uuid, uuid, text, boolean, text, text",
        ),
        # Migration 0012. Added deliberately, which is what this exact-set pin
        # exists to force. The admission role has to project the platform
        # authority's bigint-keyed identity into the certified uuid-keyed
        # tenant tables before it can admit a request at all, and the
        # alternative was granting it INSERT on users, workspaces and
        # memberships — which would let any hosted request invent a tenant.
        # This is that capability narrowed to one SECURITY DEFINER call that
        # can only write rows the caller read from the platform authority, and
        # that never updates or deletes.
        (
            "project_platform_identity",
            "uuid, text, text, text, uuid, text, text, text",
        ),
    }
)
SERVICE_ROLES = {
    "oauth": "medawarcre_oauth",
    "provider_ingress": "medawarcre_provider_ingress",
    "provider_reconcile": "medawarcre_provider_reconcile",
    "worker": "medawarcre_worker",
    "scheduler": "medawarcre_scheduler",
}
SERVICE_FUNCTIONS_BY_ROLE = {
    "medawarcre_oauth": frozenset(
        {("resolve_oauth_authority", "bytea, text, text")}
    ),
    "medawarcre_provider_ingress": frozenset(),
    "medawarcre_provider_reconcile": frozenset(),
    "medawarcre_worker": frozenset(),
    "medawarcre_scheduler": frozenset(),
}


class UnsafeDatabaseRoleError(RuntimeError):
    """A login has more authority than its one documented group role."""


def assert_exact_group_session(
    connection: psycopg.Connection,
    group_role: str,
    *,
    login_inherits: bool = False,
    group_inherits: bool = False,
    group_bypasses_rls: bool = False,
    allow_database_owner_membership: bool = False,
    allow_effective_ownership: bool = False,
) -> None:
    """Reject privileged logins, extra memberships, and unsafe group drift."""
    # SQL grammar performs this pin before any function lookup. Every caller,
    # including migration, admission, backup, restore, and dormant services,
    # therefore evaluates the preflight only against PostgreSQL's catalog.
    connection.execute("SET search_path TO pg_catalog")
    row = connection.execute(
        """
        SELECT role.rolcanlogin,
               current_user=session_user,
               role.rolinherit,
               role.rolsuper,
               role.rolbypassrls,
               role.rolcreatedb,
               role.rolcreaterole,
               role.rolreplication,
               ARRAY(
                   SELECT inherited_role.rolname
                   FROM pg_catalog.pg_roles inherited_role
                   WHERE inherited_role.rolname NOT IN (session_user, %s)
                     AND (NOT %s OR inherited_role.rolname <> 'pg_database_owner')
                     AND pg_catalog.pg_has_role(session_user, inherited_role.oid, 'member')
                   ORDER BY inherited_role.rolname
               ),
               ARRAY(
                   SELECT parent.rolname || '|' ||
                          membership.admin_option::text || '|' ||
                          membership.inherit_option::text || '|' ||
                          membership.set_option::text
                   FROM pg_catalog.pg_auth_members membership
                   JOIN pg_catalog.pg_roles parent ON parent.oid=membership.roleid
                   WHERE membership.member=role.oid
                   ORDER BY parent.rolname
               ),
               EXISTS (
                   SELECT 1 FROM pg_catalog.pg_database database
                   WHERE database.datname=pg_catalog.current_database()
                     AND database.datdba=role.oid
               ),
               EXISTS (
                   SELECT 1 FROM pg_catalog.pg_namespace namespace
                   WHERE namespace.nspname NOT IN ('pg_catalog','information_schema')
                     AND namespace.nspname NOT LIKE 'pg_toast%%'
                     AND namespace.nspname NOT LIKE 'pg_temp_%%'
                     AND namespace.nspowner=role.oid
               ),
               EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_class relation
                   JOIN pg_catalog.pg_namespace namespace
                     ON namespace.oid=relation.relnamespace
                   WHERE namespace.nspname NOT IN ('pg_catalog','information_schema')
                     AND namespace.nspname NOT LIKE 'pg_toast%%'
                     AND namespace.nspname NOT LIKE 'pg_temp_%%'
                     AND relation.relkind IN ('r','p','S','v','m','f')
                     AND relation.relowner=role.oid
               ),
               EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_proc procedure
                   JOIN pg_catalog.pg_namespace namespace
                     ON namespace.oid=procedure.pronamespace
                   WHERE namespace.nspname NOT IN ('pg_catalog','information_schema')
                     AND namespace.nspname NOT LIKE 'pg_toast%%'
                     AND namespace.nspname NOT LIKE 'pg_temp_%%'
                     AND procedure.proowner=role.oid
               ),
               EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_type type_record
                   JOIN pg_catalog.pg_namespace namespace
                     ON namespace.oid=type_record.typnamespace
                   WHERE namespace.nspname NOT IN ('pg_catalog','information_schema')
                     AND namespace.nspname NOT LIKE 'pg_toast%%'
                     AND namespace.nspname NOT LIKE 'pg_temp_%%'
                     AND type_record.typowner=role.oid
               ),
               EXISTS (
                   SELECT 1 FROM pg_catalog.pg_database database
                   WHERE database.datname=pg_catalog.current_database()
                     AND pg_catalog.pg_has_role(session_user, database.datdba, 'member')
               ),
               EXISTS (
                   SELECT 1 FROM pg_catalog.pg_namespace namespace
                   WHERE namespace.nspname NOT IN ('pg_catalog','information_schema')
                     AND namespace.nspname NOT LIKE 'pg_toast%%'
                     AND namespace.nspname NOT LIKE 'pg_temp_%%'
                     AND pg_catalog.pg_has_role(session_user, namespace.nspowner, 'member')
               ),
               EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_class relation
                   JOIN pg_catalog.pg_namespace namespace
                     ON namespace.oid=relation.relnamespace
                   WHERE namespace.nspname NOT IN ('pg_catalog','information_schema')
                     AND namespace.nspname NOT LIKE 'pg_toast%%'
                     AND namespace.nspname NOT LIKE 'pg_temp_%%'
                     AND relation.relkind IN ('r','p','S','v','m','f')
                     AND pg_catalog.pg_has_role(session_user, relation.relowner, 'member')
               ),
               EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_proc procedure
                   JOIN pg_catalog.pg_namespace namespace
                     ON namespace.oid=procedure.pronamespace
                   WHERE namespace.nspname NOT IN ('pg_catalog','information_schema')
                     AND namespace.nspname NOT LIKE 'pg_toast%%'
                     AND namespace.nspname NOT LIKE 'pg_temp_%%'
                     AND pg_catalog.pg_has_role(session_user, procedure.proowner, 'member')
               ),
               EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_type type_record
                   JOIN pg_catalog.pg_namespace namespace
                     ON namespace.oid=type_record.typnamespace
                   WHERE namespace.nspname NOT IN ('pg_catalog','information_schema')
                     AND namespace.nspname NOT LIKE 'pg_toast%%'
                     AND namespace.nspname NOT LIKE 'pg_temp_%%'
                     AND pg_catalog.pg_has_role(session_user, type_record.typowner, 'member')
               ),
               pg_catalog.has_database_privilege(
                   session_user, pg_catalog.current_database(), 'CREATE'
               ),
               EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_namespace namespace
                   WHERE namespace.nspname NOT IN ('pg_catalog','information_schema')
                     AND namespace.nspname NOT LIKE 'pg_toast%%'
                     AND namespace.nspname NOT LIKE 'pg_temp_%%'
                     AND pg_catalog.has_schema_privilege(
                         session_user, namespace.oid, 'CREATE'
                     )
               ),
               EXISTS (
                   SELECT 1
                   FROM (
                       SELECT acl.grantee
                       FROM pg_catalog.pg_database database
                       CROSS JOIN LATERAL pg_catalog.aclexplode(database.datacl) acl
                       WHERE database.datname=pg_catalog.current_database()
                       UNION ALL
                       SELECT acl.grantee
                       FROM pg_catalog.pg_namespace namespace
                       CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) acl
                       UNION ALL
                       SELECT acl.grantee
                       FROM pg_catalog.pg_class relation
                       CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) acl
                       UNION ALL
                       SELECT acl.grantee
                       FROM pg_catalog.pg_attribute attribute
                       CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) acl
                       WHERE attribute.attnum > 0 AND NOT attribute.attisdropped
                       UNION ALL
                       SELECT acl.grantee
                       FROM pg_catalog.pg_proc procedure
                       CROSS JOIN LATERAL pg_catalog.aclexplode(procedure.proacl) acl
                       UNION ALL
                       SELECT acl.grantee
                       FROM pg_catalog.pg_type type_record
                       CROSS JOIN LATERAL pg_catalog.aclexplode(type_record.typacl) acl
                       UNION ALL
                       SELECT acl.grantee
                       FROM pg_catalog.pg_default_acl default_acl
                       CROSS JOIN LATERAL pg_catalog.aclexplode(default_acl.defaclacl) acl
                   ) direct_acl
                   WHERE direct_acl.grantee=role.oid
               ),
               EXISTS (
                   SELECT 1
                   FROM (
                       SELECT acl.grantee
                       FROM pg_catalog.pg_database database
                       CROSS JOIN LATERAL pg_catalog.aclexplode(database.datacl) acl
                       WHERE database.datname=pg_catalog.current_database()
                       UNION ALL
                       SELECT acl.grantee
                       FROM pg_catalog.pg_namespace namespace
                       CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) acl
                       WHERE namespace.nspname='medawarcre'
                       UNION ALL
                       SELECT acl.grantee
                       FROM pg_catalog.pg_class relation
                       JOIN pg_catalog.pg_namespace namespace
                         ON namespace.oid=relation.relnamespace
                       CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) acl
                       WHERE namespace.nspname='medawarcre'
                       UNION ALL
                       SELECT acl.grantee
                       FROM pg_catalog.pg_attribute attribute
                       JOIN pg_catalog.pg_class relation
                         ON relation.oid=attribute.attrelid
                       JOIN pg_catalog.pg_namespace namespace
                         ON namespace.oid=relation.relnamespace
                       CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) acl
                       WHERE namespace.nspname='medawarcre'
                         AND attribute.attnum > 0 AND NOT attribute.attisdropped
                       UNION ALL
                       SELECT acl.grantee
                       FROM pg_catalog.pg_proc procedure
                       JOIN pg_catalog.pg_namespace namespace
                         ON namespace.oid=procedure.pronamespace
                       CROSS JOIN LATERAL pg_catalog.aclexplode(procedure.proacl) acl
                       WHERE namespace.nspname='medawarcre'
                       UNION ALL
                       SELECT acl.grantee
                       FROM pg_catalog.pg_type type_record
                       JOIN pg_catalog.pg_namespace namespace
                         ON namespace.oid=type_record.typnamespace
                       CROSS JOIN LATERAL pg_catalog.aclexplode(type_record.typacl) acl
                       WHERE namespace.nspname='medawarcre'
                       UNION ALL
                       SELECT acl.grantee
                       FROM pg_catalog.pg_default_acl default_acl
                       CROSS JOIN LATERAL pg_catalog.aclexplode(default_acl.defaclacl) acl
                   ) public_acl
                   WHERE public_acl.grantee=0
               ),
               EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_default_acl default_acl
                   WHERE default_acl.defaclrole=role.oid
               )
        FROM pg_catalog.pg_roles role
        WHERE role.rolname=session_user
        """,
        (group_role, allow_database_owner_membership),
    ).fetchone()
    group = connection.execute(
        "SELECT rolcanlogin,rolinherit,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,"
        "rolreplication FROM pg_catalog.pg_roles WHERE rolname=%s",
        (group_role,),
    ).fetchone()
    if row is None:
        raise UnsafeDatabaseRoleError("database authority is unavailable")
    (
        can_login,
        uses_session_authority,
        inherits_privileges,
        is_superuser,
        bypasses_rls,
        can_create_database,
        can_create_role,
        can_replicate,
        extra_memberships,
        memberships,
        directly_owns_database,
        directly_owns_schema,
        directly_owns_relation,
        directly_owns_function,
        directly_owns_type,
        owns_database,
        owns_schema,
        owns_relation,
        owns_function,
        owns_type,
        can_create_in_database,
        can_create_in_schema,
        has_direct_acl,
        has_explicit_public_acl,
        owns_default_acl,
    ) = row
    expected_membership = (
        f"{group_role}|false|{str(login_inherits).lower()}|true",
    )
    if (
        not can_login
        or not uses_session_authority
        or inherits_privileges != login_inherits
        or is_superuser
        or bypasses_rls
        or can_create_database
        or can_create_role
        or can_replicate
        or tuple(extra_memberships)
        or tuple(memberships) != expected_membership
        or directly_owns_database
        or directly_owns_schema
        or directly_owns_relation
        or directly_owns_function
        or directly_owns_type
        or can_create_in_database
        or can_create_in_schema
        or has_direct_acl
        or has_explicit_public_acl
        or owns_default_acl
        or (
            not allow_effective_ownership
            and (
                owns_database
                or owns_schema
                or owns_relation
                or owns_function
                or owns_type
            )
        )
        or group
        != (
            False,
            group_inherits,
            False,
            group_bypasses_rls,
            False,
            False,
            False,
        )
    ):
        raise UnsafeDatabaseRoleError(
            "database login violates the dedicated authority contract"
        )


def assert_admission_session(connection: psycopg.Connection) -> None:
    assert_exact_group_session(connection, ADMISSION_ROLE)


def assert_admission_object_authority(connection: psycopg.Connection) -> None:
    """Require the migrated admission group to expose only the two fixed calls."""
    _assert_group_object_authority(
        connection,
        ADMISSION_ROLE,
        ADMISSION_FUNCTIONS,
    )


def _assert_group_object_authority(
    connection: psycopg.Connection,
    group_role: str,
    expected_functions: frozenset[tuple[str, str]],
) -> None:
    """Require each service role's exact narrow object-authority contract."""
    if group_role not in {*SERVICE_ROLES.values(), ADMISSION_ROLE}:
        raise ValueError("unsupported PostgreSQL service group role")
    connection.execute("SET search_path TO pg_catalog")
    ownership = connection.execute(
        """
        SELECT
            EXISTS (
                SELECT 1
                FROM pg_catalog.pg_database database
                WHERE database.datname=pg_catalog.current_database()
                  AND database.datdba=role.oid
            )
            OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_namespace namespace
                WHERE namespace.nspowner=role.oid
                  AND namespace.nspname NOT LIKE 'pg_temp_%%'
                  AND namespace.nspname NOT LIKE 'pg_toast%%'
                  AND namespace.nspname NOT IN ('pg_catalog','information_schema')
            )
            OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class relation
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid=relation.relnamespace
                WHERE relation.relowner=role.oid
                  AND namespace.nspname NOT LIKE 'pg_temp_%%'
                  AND namespace.nspname NOT LIKE 'pg_toast%%'
                  AND namespace.nspname NOT IN ('pg_catalog','information_schema')
            )
            OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_proc procedure
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid=procedure.pronamespace
                WHERE procedure.proowner=role.oid
                  AND namespace.nspname NOT LIKE 'pg_temp_%%'
                  AND namespace.nspname NOT LIKE 'pg_toast%%'
                  AND namespace.nspname NOT IN ('pg_catalog','information_schema')
            )
            OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_type type_record
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid=type_record.typnamespace
                WHERE type_record.typowner=role.oid
                  AND namespace.nspname NOT LIKE 'pg_temp_%%'
                  AND namespace.nspname NOT LIKE 'pg_toast%%'
                  AND namespace.nspname NOT IN ('pg_catalog','information_schema')
            )
            OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_default_acl default_acl
                WHERE default_acl.defaclrole=role.oid
            )
            OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_default_acl default_acl
                CROSS JOIN LATERAL pg_catalog.aclexplode(
                    default_acl.defaclacl
                ) acl
                WHERE acl.grantee=role.oid
            )
        FROM pg_catalog.pg_roles role
        WHERE role.rolname=%s
        """,
        (group_role,),
    ).fetchone()
    if ownership is None or bool(ownership[0]):
        raise UnsafeDatabaseRoleError(
            "service group role violates the exact authority contract"
        )

    direct_acl = {
        tuple(row)
        for row in connection.execute(
            """
            SELECT object_type,schema_name,object_name,privilege_type,
                   is_grantable,grantor_name
            FROM (
                SELECT 'database'::text AS object_type,
                       ''::text AS schema_name,
                       database.datname::text AS object_name,
                       acl.privilege_type::text AS privilege_type,
                       acl.is_grantable,
                       grantor.rolname::text AS grantor_name,
                       acl.grantee
                FROM pg_catalog.pg_database database
                CROSS JOIN LATERAL pg_catalog.aclexplode(database.datacl) acl
                JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
                WHERE database.datname=pg_catalog.current_database()
                UNION ALL
                SELECT 'schema',namespace.nspname,'',acl.privilege_type,
                       acl.is_grantable,grantor.rolname,acl.grantee
                FROM pg_catalog.pg_namespace namespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) acl
                JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
                UNION ALL
                SELECT 'relation',namespace.nspname,relation.relname,
                       acl.privilege_type,acl.is_grantable,grantor.rolname,
                       acl.grantee
                FROM pg_catalog.pg_class relation
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid=relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) acl
                JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
                UNION ALL
                SELECT 'column',namespace.nspname,
                       relation.relname || '.' || attribute.attname,
                       acl.privilege_type,acl.is_grantable,grantor.rolname,
                       acl.grantee
                FROM pg_catalog.pg_attribute attribute
                JOIN pg_catalog.pg_class relation
                  ON relation.oid=attribute.attrelid
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid=relation.relnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) acl
                JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
                WHERE attribute.attnum > 0 AND NOT attribute.attisdropped
                UNION ALL
                SELECT 'function',namespace.nspname,
                       procedure.proname || '|' ||
                       pg_catalog.oidvectortypes(procedure.proargtypes),
                       acl.privilege_type,acl.is_grantable,grantor.rolname,
                       acl.grantee
                FROM pg_catalog.pg_proc procedure
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid=procedure.pronamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(procedure.proacl) acl
                JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
                UNION ALL
                SELECT 'type',namespace.nspname,type_record.typname,
                       acl.privilege_type,acl.is_grantable,grantor.rolname,
                       acl.grantee
                FROM pg_catalog.pg_type type_record
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid=type_record.typnamespace
                CROSS JOIN LATERAL pg_catalog.aclexplode(type_record.typacl) acl
                JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
            ) object_acl
            JOIN pg_catalog.pg_roles role ON role.oid=object_acl.grantee
            WHERE role.rolname=%s
            ORDER BY object_type,schema_name,object_name,privilege_type
            """,
            (group_role,),
        ).fetchall()
    }
    expected_acl = {
        (
            "function",
            "medawarcre",
            f"{function_name}|{argument_types}",
            "EXECUTE",
            False,
            "medawarcre_migration",
        )
        for function_name, argument_types in expected_functions
    }
    if expected_functions:
        expected_acl.add(
            (
                "schema",
                "medawarcre",
                "",
                "USAGE",
                False,
                "medawarcre_migration",
            )
        )
    if direct_acl != expected_acl:
        raise UnsafeDatabaseRoleError(
            "service group role violates the exact authority contract"
        )


def assert_group_has_no_object_authority(
    connection: psycopg.Connection,
    group_role: str,
) -> None:
    """Require a clean bootstrap role with no object authority."""
    _assert_group_object_authority(connection, group_role, frozenset())


def assert_group_has_exact_object_authority(
    connection: psycopg.Connection,
    group_role: str,
) -> None:
    """Require the reviewed function-only authority for a service role."""
    try:
        expected_functions = SERVICE_FUNCTIONS_BY_ROLE[group_role]
    except KeyError as error:
        raise ValueError("unsupported PostgreSQL service group role") from error
    _assert_group_object_authority(connection, group_role, expected_functions)


def assert_service_session(
    connection: psycopg.Connection,
    service: str,
) -> None:
    """Require the one non-inheriting group role for a hosted service."""
    try:
        group_role = SERVICE_ROLES[service]
    except KeyError as error:
        raise ValueError("unsupported PostgreSQL service identity") from error
    assert_exact_group_session(connection, group_role)
    assert_group_has_exact_object_authority(connection, group_role)


__all__ = [
    "ADMISSION_FUNCTIONS",
    "ADMISSION_ROLE",
    "SERVICE_ROLES",
    "SERVICE_FUNCTIONS_BY_ROLE",
    "UnsafeDatabaseRoleError",
    "assert_admission_session",
    "assert_admission_object_authority",
    "assert_exact_group_session",
    "assert_group_has_exact_object_authority",
    "assert_group_has_no_object_authority",
    "assert_service_session",
]
