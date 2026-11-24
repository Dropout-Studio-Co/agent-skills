"""Tenant file exports."""
import os

ROOT = "/srv/exports"


def tenant_root(tenant):
    """Resolve the tenant's directory, following symlinks."""
    return os.path.realpath(os.path.join(ROOT, tenant))


def export_path(tenant, relative):
    """Return the on-disk path of one tenant export, refusing traversal and symlink escapes."""
    base = tenant_root(tenant)
    target = os.path.realpath(os.path.join(base, relative))
    if os.path.commonpath([base, target]) != base:
        raise ValueError("path escapes the tenant directory: %r" % relative)
    return target
