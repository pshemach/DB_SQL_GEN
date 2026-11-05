# MySQL Restore Guide for `samindu_live`

Use this guide **after the dump file is already uploaded** to the Linux server.

Dump file:

```text
samindu_live.sql
```

Recommended server path:

```bash
/root/Desktop/ML-Projects/SFASmartAnalyst/data/samindu_live.sql
```

The project and SQL dump are in this folder on the server.

This dump is about **1.1 GB**. Do **not** paste it into the MySQL terminal. Do **not** use a plain `SOURCE` without the wrapper settings below.

---

## Why a normal restore fails

A plain `SOURCE samindu_live.sql;` often fails, and `external_parties` is the table that usually goes missing.

The dump has these problems:

1. **`external_parties` row size is too large**
   - The table has 40+ `VARCHAR(255)` columns.
   - Linux MySQL may throw:

```text
ERROR 1118 (42000): Row size too large (> 8126)
```

   - After that, inserts fail with:

```text
ERROR 1146 (42S02): Table 'samindu_live.external_parties' doesn't exist
```

2. **Circular foreign keys**
   - `external_parties` references `users`
   - `users` references `external_parties`

3. **GTID statement at the top of the dump**
   - This line often fails on a different server:

```sql
SET @@GLOBAL.GTID_PURGED=...
```

4. **Very large INSERT lines**
   - Restore can fail if `max_allowed_packet` is too small.

The steps below fix all of these.

---

## Step 1. SSH into the server

```bash
ssh root@YOUR_SERVER_IP
```

---

## Step 2. Confirm the uploaded dump exists

```bash
ls -lh /root/Desktop/ML-Projects/SFASmartAnalyst/data/samindu_live.sql
```

Expected: the file exists and is around **1.1 GB**.

If `No such file or directory` appears, find it:

```bash
find /root/Desktop/ML-Projects/SFASmartAnalyst -name "samindu_live.sql"
```

Then use that path in every command below.

---

## Step 3. Confirm MySQL is running

```bash
systemctl status mysql --no-pager
```

If MySQL is not installed as `mysql`, try:

```bash
systemctl status mariadb --no-pager
```

Start it if needed:

```bash
systemctl start mysql
```

Check that you can log in:

```bash
mysql -u root -p -e "SELECT VERSION();"
```

Enter the MySQL root password when asked.

---

## Step 4. Increase packet size for this restore

The dump contains very large `INSERT` lines. Raise the limit before restore:

```bash
mysql -u root -p -e "SET GLOBAL max_allowed_packet=1073741824;"
```

That sets `max_allowed_packet` to 1 GB.

---

## Step 5. Go to the data folder

```bash
mkdir -p /root/Desktop/ML-Projects/SFASmartAnalyst/data
cd /root/Desktop/ML-Projects/SFASmartAnalyst/data
```

---

## Step 6. Create a cleaned dump without the GTID line

The GTID line can abort restore on a different Linux server. Create a cleaned copy:

```bash
grep -v "GTID_PURGED" samindu_live.sql > samindu_live_cleaned.sql
```

This can take a few minutes because the file is large.

Confirm the cleaned file exists:

```bash
ls -lh samindu_live_cleaned.sql
```

---

## Step 7. Add `ROW_FORMAT=DYNAMIC` so `external_parties` can be created

```bash
sed -i 's/ENGINE=InnoDB DEFAULT CHARSET=latin1;/ENGINE=InnoDB DEFAULT CHARSET=latin1 ROW_FORMAT=DYNAMIC;/g' samindu_live_cleaned.sql
```

This helps InnoDB store the large `external_parties` row definition.

---

## Step 8. Create the restore wrapper

This wrapper turns off the two settings that cause table-create failures:

```bash
echo "SET SESSION innodb_strict_mode=OFF;" > restore_wrapper.sql
echo "SET FOREIGN_KEY_CHECKS=0;" >> restore_wrapper.sql
echo "SET UNIQUE_CHECKS=0;" >> restore_wrapper.sql
echo "SET SESSION sql_log_bin=0;" >> restore_wrapper.sql
cat samindu_live_cleaned.sql >> restore_wrapper.sql
echo "SET UNIQUE_CHECKS=1;" >> restore_wrapper.sql
echo "SET FOREIGN_KEY_CHECKS=1;" >> restore_wrapper.sql
```

This concatenates a 1.1 GB file, so it can take a few minutes.

Confirm the wrapper exists:

```bash
ls -lh restore_wrapper.sql
head -n 10 restore_wrapper.sql
```

The first lines must be:

```sql
SET SESSION innodb_strict_mode=OFF;
SET FOREIGN_KEY_CHECKS=0;
SET UNIQUE_CHECKS=0;
SET SESSION sql_log_bin=0;
```

---

## Step 9. Drop and recreate the database

This deletes the old `samindu_live` database if it exists.

```bash
mysql -u root -p -e "DROP DATABASE IF EXISTS samindu_live; CREATE DATABASE samindu_live CHARACTER SET latin1 COLLATE latin1_swedish_ci;"
```

Confirm:

```bash
mysql -u root -p -e "SHOW DATABASES LIKE 'samindu_live';"
```

---

## Step 10. Start a long-running session

Restore can take a long time. Use `tmux` or `screen` so SSH disconnect does not kill it.

If `tmux` is available:

```bash
tmux new -s mysql_restore
```

If `tmux` is not installed:

```bash
apt-get update && apt-get install -y tmux
tmux new -s mysql_restore
```

If the SSH session drops later, reconnect with:

```bash
tmux attach -t mysql_restore
```

---

## Step 11. Restore the database

From:

```bash
cd /root/Desktop/ML-Projects/SFASmartAnalyst/data
```

run:

```bash
mysql -u root -p --force samindu_live < restore_wrapper.sql > restore_output.log 2> restore_error.log
```

`--force` tells MySQL to continue if a non-fatal statement fails.

This step can take a long time. Wait until the command finishes and returns to the shell prompt.

Do **not** close the terminal while it is running.

---

## Step 12. Check the error log

```bash
cd /root/Desktop/ML-Projects/SFASmartAnalyst/data
wc -l restore_error.log
grep -E "ERROR|external_parties|Row size too large|doesn't exist" restore_error.log | head -n 50
```

What the result means:

- No `ERROR` lines, or only harmless warnings: restore succeeded.
- `Row size too large`: `external_parties` still failed. Recheck Step 7 and Step 8.
- `Table 'samindu_live.external_parties' doesn't exist`: the `CREATE TABLE` for that table failed earlier.
- `GTID_PURGED`: Step 6 did not remove the GTID line.

To inspect the full log:

```bash
less restore_error.log
```

Press `q` to quit `less`.

---

## Step 13. Verify the important tables

```bash
mysql -u root -p samindu_live -e "SHOW TABLES LIKE 'external_parties'; SHOW TABLES LIKE 'users'; SHOW TABLES LIKE 'sales_flat'; SELECT COUNT(*) AS external_parties_count FROM external_parties; SELECT COUNT(*) AS users_count FROM users;"
```

Expected:

- `external_parties` table exists
- `users` table exists
- `sales_flat` table exists
- row counts are returned, not an error

Count all tables:

```bash
mysql -u root -p samindu_live -e "SELECT COUNT(*) AS table_count FROM information_schema.tables WHERE table_schema = 'samindu_live';"
```

List tables whose names contain `external`:

```bash
mysql -u root -p samindu_live -e "SHOW TABLES LIKE 'external%';"
```

The customer/distributor table name is:

```text
external_parties
```

It is **not** `external_partes`. Linux table names are case-sensitive.

---

## Step 14. If `external_parties` is still missing

Run the checks below.

### 14.1 Confirm the wrapper starts with the required settings

```bash
head -n 8 /root/Desktop/ML-Projects/SFASmartAnalyst/data/restore_wrapper.sql
```

If `SET SESSION innodb_strict_mode=OFF;` is not first, redo Step 8.

### 14.2 Confirm `ROW_FORMAT=DYNAMIC` was applied

```bash
grep -n "CREATE TABLE \`external_parties\`" -A 220 /root/Desktop/ML-Projects/SFASmartAnalyst/data/restore_wrapper.sql | tail -n 5
```

The `ENGINE=` line should include `ROW_FORMAT=DYNAMIC`.

### 14.3 Recreate only the missing table after a failed restore

If other tables restored but `external_parties` did not, drop the database and restore again from Step 8. Do not try to paste the `CREATE TABLE` into the MySQL prompt. That table definition is too large, and the INSERT data is huge.

If you only need to retry after a partial restore:

```bash
mysql -u root -p -e "DROP DATABASE IF EXISTS samindu_live; CREATE DATABASE samindu_live CHARACTER SET latin1 COLLATE latin1_swedish_ci;"

cd /root/Desktop/ML-Projects/SFASmartAnalyst/data
mysql -u root -p --force samindu_live < restore_wrapper.sql > restore_output.log 2> restore_error.log
```

---

## Step 15. Optional cleanup

After a successful restore, you can delete the extra files to save disk space. Keep the original dump.

```bash
cd /root/Desktop/ML-Projects/SFASmartAnalyst/data
rm -f samindu_live_cleaned.sql restore_wrapper.sql restore_output.log restore_error.log
```

Do **not** delete `samindu_live.sql` until you are sure the restore is good.

---

## Commands you should not use

Do not paste the dump into MySQL.

Do not run only this:

```sql
SOURCE /root/Desktop/ML-Projects/SFASmartAnalyst/data/samindu_live.sql;
```

That skips the row-size and foreign-key fixes, so `external_parties` is likely to be missing.

Do not restore into the wrong database. Always pass `samindu_live` to the `mysql` command, or run `USE samindu_live;` first.

---

## Why these settings are required

### `SET SESSION innodb_strict_mode=OFF`

Allows MySQL to create `external_parties` even though the row definition is larger than InnoDB’s compact 8126-byte limit.

### `ROW_FORMAT=DYNAMIC`

Stores large `VARCHAR` columns off-page so `external_parties` can be created on a typical Linux InnoDB setup.

### `SET FOREIGN_KEY_CHECKS=0`

Allows tables to be created even with circular foreign keys:

```text
external_parties -> users
users -> external_parties
```

The original dump already sets this, but the wrapper makes it explicit before any `CREATE TABLE`.

### `--force`

Continues restore if a non-fatal statement fails, instead of stopping halfway.

### Remove `GTID_PURGED`

The dump was taken from a GTID-enabled server. Restoring that statement onto a different Linux server often fails immediately.

---

## Quick copy-paste sequence

After the dump is uploaded to:

```text
/root/Desktop/ML-Projects/SFASmartAnalyst/data/samindu_live.sql
```

run these commands in order:

```bash
cd /root/Desktop/ML-Projects/SFASmartAnalyst/data

mysql -u root -p -e "SET GLOBAL max_allowed_packet=1073741824;"

grep -v "GTID_PURGED" samindu_live.sql > samindu_live_cleaned.sql

sed -i 's/ENGINE=InnoDB DEFAULT CHARSET=latin1;/ENGINE=InnoDB DEFAULT CHARSET=latin1 ROW_FORMAT=DYNAMIC;/g' samindu_live_cleaned.sql

echo "SET SESSION innodb_strict_mode=OFF;" > restore_wrapper.sql
echo "SET FOREIGN_KEY_CHECKS=0;" >> restore_wrapper.sql
echo "SET UNIQUE_CHECKS=0;" >> restore_wrapper.sql
echo "SET SESSION sql_log_bin=0;" >> restore_wrapper.sql
cat samindu_live_cleaned.sql >> restore_wrapper.sql
echo "SET UNIQUE_CHECKS=1;" >> restore_wrapper.sql
echo "SET FOREIGN_KEY_CHECKS=1;" >> restore_wrapper.sql

mysql -u root -p -e "DROP DATABASE IF EXISTS samindu_live; CREATE DATABASE samindu_live CHARACTER SET latin1 COLLATE latin1_swedish_ci;"

mysql -u root -p --force samindu_live < restore_wrapper.sql > restore_output.log 2> restore_error.log

grep -E "ERROR|external_parties|Row size too large|doesn't exist" restore_error.log | head -n 50

mysql -u root -p samindu_live -e "SHOW TABLES LIKE 'external_parties'; SHOW TABLES LIKE 'users'; SELECT COUNT(*) FROM external_parties; SELECT COUNT(*) FROM users;"
```

If `external_parties` exists and `COUNT(*)` returns a number, the restore succeeded.
