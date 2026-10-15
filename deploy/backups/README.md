# FreqID Backups Directory

This directory stores automated encrypted database dumps produced by `deploy/scripts/backup.sh`.

## Backup File Format

- Artifact: `freqid_backup_YYYYMMDD_HHMMSSZ.dump.enc`
- Checksum: `freqid_backup_YYYYMMDD_HHMMSSZ.dump.enc.sha256`
- Encryption: AES-256-CBC with PBKDF2 (100,000 iterations) using the key in `deploy/secrets/backup.key`.

## Execution

- **Create Backup**: `./deploy/scripts/backup.sh`
- **Restore Backup**: `./deploy/scripts/restore.sh --file deploy/backups/freqid_backup_<timestamp>.dump.enc`

## Security Notice

Database dumps and keys are strictly excluded from source control by `.gitignore` to prevent data leakage.
