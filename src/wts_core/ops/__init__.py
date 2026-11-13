"""Backup, restore, off-site copies and the warnings when they stop: what keeps the state database safe.

The site describes its backups once, in a ``BackupSpec``, and passes it to each function here. Its own commands
(``wts_core.cli`` has the shared ones) print the outcome in the site's words; unit and timer files stay in each
site's ``deploy/``. Nothing here imports an outside library: the off-site store is a ``ports.OffsiteStore``
(``wts_core.adapters.b2`` for Backblaze B2).
"""

from wts_core.ops.backup import BackupSpec, RestoreRefused, make_backup, restore_backup
from wts_core.ops.offsite import (
    Alert,
    AlertWording,
    OffsiteError,
    OffsiteUnavailable,
    backup_alerts,
    check_offsite,
    send_offsite,
)

__all__ = [
    "Alert",
    "AlertWording",
    "BackupSpec",
    "OffsiteError",
    "OffsiteUnavailable",
    "RestoreRefused",
    "backup_alerts",
    "check_offsite",
    "make_backup",
    "restore_backup",
    "send_offsite",
]
