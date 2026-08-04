"""Deterministic PostgreSQL catalog contract for launch-schema drift checks."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg

from cre_mcp.postgres.schema import SCHEMA_NAME

_CONTRACT_ROLES = (
    "medawarcre_admission",
    "medawarcre_admin",
    "medawarcre_app",
    "medawarcre_backup",
    "medawarcre_migration",
    "medawarcre_oauth",
    "medawarcre_provider_ingress",
    "medawarcre_provider_reconcile",
    "medawarcre_scheduler",
    "medawarcre_worker",
)


def _normalized_rows(rows: list[tuple[Any, ...]]) -> tuple[tuple[Any, ...], ...]:
    def normalize(value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return tuple(normalize(item) for item in value)
        return value

    return tuple(tuple(normalize(value) for value in row) for row in rows)


def catalog_contract(connection: psycopg.Connection) -> dict[str, Any]:
    """Return a stable, OID-free description of every enforced schema surface."""
    queries = {
        "database": """
            SELECT owner.rolname, database.datallowconn, database.datconnlimit,
                   ARRAY(
                       SELECT grantor.rolname || '>' ||
                              CASE WHEN acl.grantee=0 THEN 'PUBLIC'
                                   ELSE grantee.rolname END || ':' ||
                              acl.privilege_type || ':' || acl.is_grantable::text
                       FROM pg_catalog.aclexplode(
                           COALESCE(database.datacl,
                                    pg_catalog.acldefault('d', database.datdba))) acl
                       JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
                       LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee
                       ORDER BY grantor.rolname,
                                CASE WHEN acl.grantee=0 THEN 'PUBLIC'
                                     ELSE grantee.rolname END,
                                acl.privilege_type, acl.is_grantable
                   )
            FROM pg_catalog.pg_database database
            JOIN pg_catalog.pg_roles owner ON owner.oid=database.datdba
            WHERE database.datname=current_database()
        """,
        "role_contract": """
            SELECT role.rolname, role.rolcanlogin, role.rolinherit,
                   role.rolsuper, role.rolbypassrls, role.rolcreatedb,
                   role.rolcreaterole, role.rolreplication
            FROM pg_catalog.pg_roles role
            WHERE role.rolname = ANY(%s)
            ORDER BY role.rolname
        """,
        "group_memberships": """
            SELECT member.rolname, parent.rolname,
                   membership.admin_option, membership.inherit_option,
                   membership.set_option
            FROM pg_catalog.pg_auth_members membership
            JOIN pg_catalog.pg_roles member ON member.oid=membership.member
            JOIN pg_catalog.pg_roles parent ON parent.oid=membership.roleid
            WHERE member.rolname = ANY(%s)
            ORDER BY member.rolname, parent.rolname
        """,
        "tables": """
            SELECT relation.relname, relation.relkind, relation.relpersistence,
                   relation.relrowsecurity, relation.relforcerowsecurity,
                   relation.relreplident, owner.rolname
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid=relation.relnamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid=relation.relowner
            WHERE namespace.nspname=%s AND relation.relkind IN ('r','p')
            ORDER BY relation.relname
        """,
        "columns": """
            SELECT relation.relname, attribute.attnum, attribute.attname,
                   pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
                   attribute.attnotnull, attribute.attidentity,
                   attribute.attgenerated,
                   COALESCE(pg_catalog.pg_get_expr(default_value.adbin,
                                                   default_value.adrelid, true), ''),
                   COALESCE(collation_namespace.nspname || '.' ||
                            collation_record.collname, '')
            FROM pg_catalog.pg_attribute attribute
            JOIN pg_catalog.pg_class relation ON relation.oid=attribute.attrelid
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid=relation.relnamespace
            LEFT JOIN pg_catalog.pg_attrdef default_value
              ON default_value.adrelid=attribute.attrelid
             AND default_value.adnum=attribute.attnum
            LEFT JOIN pg_catalog.pg_collation collation_record
              ON collation_record.oid=attribute.attcollation
            LEFT JOIN pg_catalog.pg_namespace collation_namespace
              ON collation_namespace.oid=collation_record.collnamespace
            WHERE namespace.nspname=%s AND relation.relkind IN ('r','p')
              AND attribute.attnum > 0 AND NOT attribute.attisdropped
            ORDER BY relation.relname, attribute.attnum
        """,
        "constraints": """
            SELECT relation.relname, constraint_record.conname,
                   constraint_record.contype, constraint_record.condeferrable,
                   constraint_record.condeferred, constraint_record.convalidated,
                   constraint_record.connoinherit,
                   pg_catalog.pg_get_constraintdef(constraint_record.oid, true)
            FROM pg_catalog.pg_constraint constraint_record
            JOIN pg_catalog.pg_class relation
              ON relation.oid=constraint_record.conrelid
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid=relation.relnamespace
            WHERE namespace.nspname=%s AND relation.relkind IN ('r','p')
            ORDER BY relation.relname, constraint_record.conname
        """,
        "indexes": """
            SELECT relation.relname, index_relation.relname, method.amname,
                   index_record.indisunique, index_record.indisprimary,
                   index_record.indisvalid, index_record.indisready,
                   index_record.indisreplident,
                   pg_catalog.pg_get_indexdef(index_record.indexrelid, 0, true),
                   COALESCE(pg_catalog.pg_get_expr(index_record.indpred,
                                                   index_record.indrelid, true), '')
            FROM pg_catalog.pg_index index_record
            JOIN pg_catalog.pg_class relation ON relation.oid=index_record.indrelid
            JOIN pg_catalog.pg_class index_relation
              ON index_relation.oid=index_record.indexrelid
            JOIN pg_catalog.pg_am method ON method.oid=index_relation.relam
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid=relation.relnamespace
            WHERE namespace.nspname=%s AND relation.relkind IN ('r','p')
            ORDER BY relation.relname, index_relation.relname
        """,
        "policies": """
            SELECT relation.relname, policy.polname, policy.polpermissive,
                   policy.polcmd,
                   ARRAY(
                       SELECT CASE WHEN role_oid=0 THEN 'PUBLIC' ELSE role.rolname END
                       FROM unnest(policy.polroles) role_oid
                       LEFT JOIN pg_catalog.pg_roles role ON role.oid=role_oid
                       ORDER BY CASE WHEN role_oid=0 THEN 'PUBLIC' ELSE role.rolname END
                   ),
                   COALESCE(pg_catalog.pg_get_expr(policy.polqual,
                                                   policy.polrelid, true), ''),
                   COALESCE(pg_catalog.pg_get_expr(policy.polwithcheck,
                                                   policy.polrelid, true), '')
            FROM pg_catalog.pg_policy policy
            JOIN pg_catalog.pg_class relation ON relation.oid=policy.polrelid
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid=relation.relnamespace
            WHERE namespace.nspname=%s
            ORDER BY relation.relname, policy.polname
        """,
        "triggers": """
            SELECT relation.relname, trigger_record.tgname,
                   trigger_record.tgenabled, trigger_record.tgtype,
                   pg_catalog.pg_get_triggerdef(trigger_record.oid, true)
            FROM pg_catalog.pg_trigger trigger_record
            JOIN pg_catalog.pg_class relation
              ON relation.oid=trigger_record.tgrelid
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid=relation.relnamespace
            WHERE namespace.nspname=%s AND NOT trigger_record.tgisinternal
            ORDER BY relation.relname, trigger_record.tgname
        """,
        "functions": """
            SELECT procedure.proname,
                   pg_catalog.pg_get_function_identity_arguments(procedure.oid),
                   pg_catalog.pg_get_function_arguments(procedure.oid),
                   pg_catalog.pg_get_function_result(procedure.oid),
                   language.lanname, procedure.prokind, procedure.provolatile,
                   procedure.proparallel, procedure.proisstrict,
                   procedure.prosecdef, procedure.proleakproof,
                   procedure.proretset,
                   ARRAY(
                       SELECT setting
                       FROM unnest(COALESCE(procedure.proconfig,
                                            ARRAY[]::text[])) setting
                       ORDER BY setting
                   ),
                   procedure.prosrc, owner.rolname
            FROM pg_catalog.pg_proc procedure
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid=procedure.pronamespace
            JOIN pg_catalog.pg_language language ON language.oid=procedure.prolang
            JOIN pg_catalog.pg_roles owner ON owner.oid=procedure.proowner
            WHERE namespace.nspname=%s
            ORDER BY procedure.proname,
                     pg_catalog.pg_get_function_identity_arguments(procedure.oid)
        """,
        "table_acl": """
            SELECT relation.relname, grantor.rolname,
                   CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END,
                   acl.privilege_type, acl.is_grantable
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid=relation.relnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(relation.relacl,
                         pg_catalog.acldefault('r', relation.relowner))) acl
            JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
            LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee
            WHERE namespace.nspname=%s AND relation.relkind IN ('r','p')
            ORDER BY relation.relname, grantor.rolname,
                     CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END,
                     acl.privilege_type, acl.is_grantable
        """,
        "column_acl": """
            SELECT relation.relname, attribute.attname, grantor.rolname,
                   CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END,
                   acl.privilege_type, acl.is_grantable
            FROM pg_catalog.pg_attribute attribute
            JOIN pg_catalog.pg_class relation ON relation.oid=attribute.attrelid
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid=relation.relnamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) acl
            JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
            LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee
            WHERE namespace.nspname=%s AND relation.relkind IN ('r','p')
              AND attribute.attnum > 0 AND NOT attribute.attisdropped
            ORDER BY relation.relname, attribute.attnum, grantor.rolname,
                     CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END,
                     acl.privilege_type, acl.is_grantable
        """,
        "function_acl": """
            SELECT procedure.proname,
                   pg_catalog.pg_get_function_identity_arguments(procedure.oid),
                   grantor.rolname,
                   CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END,
                   acl.privilege_type, acl.is_grantable
            FROM pg_catalog.pg_proc procedure
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid=procedure.pronamespace
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(procedure.proacl,
                         pg_catalog.acldefault('f', procedure.proowner))) acl
            JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
            LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee
            WHERE namespace.nspname=%s
            ORDER BY procedure.proname,
                     pg_catalog.pg_get_function_identity_arguments(procedure.oid),
                     grantor.rolname,
                     CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END,
                     acl.privilege_type, acl.is_grantable
        """,
        "schema_acl": """
            SELECT owner.rolname, grantor.rolname,
                   CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END,
                   acl.privilege_type, acl.is_grantable
            FROM pg_catalog.pg_namespace namespace
            JOIN pg_catalog.pg_roles owner ON owner.oid=namespace.nspowner
            CROSS JOIN LATERAL pg_catalog.aclexplode(
                COALESCE(namespace.nspacl,
                         pg_catalog.acldefault('n', namespace.nspowner))) acl
            JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
            LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee
            WHERE namespace.nspname=%s
            ORDER BY owner.rolname, grantor.rolname,
                     CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END,
                     acl.privilege_type, acl.is_grantable
        """,
        "sequences": """
            SELECT relation.relname, relation.relpersistence, owner.rolname,
                   ARRAY(
                       SELECT grantor.rolname || '>' ||
                              CASE WHEN acl.grantee=0 THEN 'PUBLIC'
                                   ELSE grantee.rolname END || ':' ||
                              acl.privilege_type || ':' || acl.is_grantable::text
                       FROM pg_catalog.aclexplode(
                           COALESCE(relation.relacl,
                                    pg_catalog.acldefault('S', relation.relowner))) acl
                       JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
                       LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee
                       ORDER BY grantor.rolname,
                                CASE WHEN acl.grantee=0 THEN 'PUBLIC'
                                     ELSE grantee.rolname END,
                                acl.privilege_type, acl.is_grantable
                   )
            FROM pg_catalog.pg_class relation
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid=relation.relnamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid=relation.relowner
            WHERE namespace.nspname=%s AND relation.relkind='S'
            ORDER BY relation.relname
        """,
        "types": """
            SELECT type_record.typname, type_record.typtype, type_record.typcategory,
                   type_record.typnotnull, owner.rolname,
                   ARRAY(
                       SELECT grantor.rolname || '>' ||
                              CASE WHEN acl.grantee=0 THEN 'PUBLIC'
                                   ELSE grantee.rolname END || ':' ||
                              acl.privilege_type || ':' || acl.is_grantable::text
                       FROM pg_catalog.aclexplode(
                           COALESCE(type_record.typacl,
                                    pg_catalog.acldefault('T', type_record.typowner))) acl
                       JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
                       LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee
                       ORDER BY grantor.rolname,
                                CASE WHEN acl.grantee=0 THEN 'PUBLIC'
                                     ELSE grantee.rolname END,
                                acl.privilege_type, acl.is_grantable
                   )
            FROM pg_catalog.pg_type type_record
            JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid=type_record.typnamespace
            JOIN pg_catalog.pg_roles owner ON owner.oid=type_record.typowner
            WHERE namespace.nspname=%s
            ORDER BY type_record.typname
        """,
        "default_acl": """
            SELECT owner.rolname, COALESCE(namespace.nspname, ''),
                   default_acl.defaclobjtype,
                   ARRAY(
                       SELECT grantor.rolname || '>' ||
                              CASE WHEN acl.grantee=0 THEN 'PUBLIC'
                                   ELSE grantee.rolname END || ':' ||
                              acl.privilege_type || ':' || acl.is_grantable::text
                       FROM pg_catalog.aclexplode(default_acl.defaclacl) acl
                       JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor
                       LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee
                       ORDER BY grantor.rolname,
                                CASE WHEN acl.grantee=0 THEN 'PUBLIC'
                                     ELSE grantee.rolname END,
                                acl.privilege_type, acl.is_grantable
                   )
            FROM pg_catalog.pg_default_acl default_acl
            JOIN pg_catalog.pg_roles owner ON owner.oid=default_acl.defaclrole
            LEFT JOIN pg_catalog.pg_namespace namespace
              ON namespace.oid=default_acl.defaclnamespace
            WHERE owner.rolname = ANY(%s) OR namespace.nspname=%s
            ORDER BY owner.rolname, COALESCE(namespace.nspname, ''),
                     default_acl.defaclobjtype
        """,
    }
    role_parameters = (list(_CONTRACT_ROLES),)
    parameters = {
        "database": (),
        "role_contract": role_parameters,
        "group_memberships": role_parameters,
        "default_acl": (*role_parameters, SCHEMA_NAME),
    }
    return {
        name: _normalized_rows(
            connection.execute(
                statement, parameters.get(name, (SCHEMA_NAME,))
            ).fetchall()
        )
        for name, statement in queries.items()
    }


def catalog_fingerprint(connection: psycopg.Connection) -> str:
    payload = json.dumps(
        catalog_contract(connection),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = ["catalog_contract", "catalog_fingerprint"]
