# MySQL Restore Instructions for `samindu_live`

## Issue Summary

When restoring the `samindu_live` database from the SQL dump, a normal `SOURCE file.sql` may fail.

The dump has two main issues:

1. **Circular foreign key dependency**
   - `external_parties` references `users`
   - `users` references `external_parties`
   - Because of this, foreign key checks must be disabled during the full restore.

2. **Row size too large error**
   - `external_parties` has many large `VARCHAR` columns.
   - MySQL may throw this error:

```text
ERROR 1118 (42000): Row size too large (> 8126)
```

To avoid this, restore using `innodb_strict_mode=OFF`.

---

## SQL Dump File Path

```bash
/root/Desktop/ML-Projects/DB_SQL_GEN/samindu_live_2025_june_20260630_112909.sql
```

---

## Recommended Restore Method

### 1. Create a restore wrapper file

Run this from the Linux terminal:

```bash
echo "SET SESSION innodb_strict_mode=OFF;" > /root/Desktop/ML-Projects/DB_SQL_GEN/restore_wrapper.sql

echo "SET FOREIGN_KEY_CHECKS=0;" >> /root/Desktop/ML-Projects/DB_SQL_GEN/restore_wrapper.sql

cat /root/Desktop/ML-Projects/DB_SQL_GEN/samindu_live_2025_june_20260630_112909.sql >> /root/Desktop/ML-Projects/DB_SQL_GEN/restore_wrapper.sql

echo "SET FOREIGN_KEY_CHECKS=1;" >> /root/Desktop/ML-Projects/DB_SQL_GEN/restore_wrapper.sql
```

---

### 2. Drop and recreate the database

```bash
mysql -u root -p -e "DROP DATABASE IF EXISTS samindu_live; CREATE DATABASE samindu_live CHARACTER SET latin1 COLLATE latin1_swedish_ci;"
```

---

### 3. Restore the database using the wrapper file

```bash
mysql -u root -p samindu_live < /root/Desktop/ML-Projects/DB_SQL_GEN/restore_wrapper.sql > /root/Desktop/ML-Projects/DB_SQL_GEN/restore_output.log 2> /root/Desktop/ML-Projects/DB_SQL_GEN/restore_error.log
```

---

### 4. Check restore errors

```bash
cat /root/Desktop/ML-Projects/DB_SQL_GEN/restore_error.log
```

If this file is empty, the restore completed without errors.

---

### 5. Verify important tables

```bash
mysql -u root -p samindu_live -e "SHOW TABLES LIKE 'external_parties'; SHOW TABLES LIKE 'users'; SELECT COUNT(*) FROM external_parties; SELECT COUNT(*) FROM users;"
```

Expected result:

- `external_parties` table should exist
- `users` table should exist
- Both tables should return row counts

---

## If Row Size Error Still Happens

Create a fixed SQL file by adding `ROW_FORMAT=DYNAMIC` to InnoDB table definitions.

### 1. Copy the original dump

```bash
cp /root/Desktop/ML-Projects/DB_SQL_GEN/samindu_live_2025_june_20260630_112909.sql /root/Desktop/ML-Projects/DB_SQL_GEN/samindu_live_fixed.sql
```

### 2. Add `ROW_FORMAT=DYNAMIC`

```bash
sed -i 's/ENGINE=InnoDB DEFAULT CHARSET=latin1;/ENGINE=InnoDB DEFAULT CHARSET=latin1 ROW_FORMAT=DYNAMIC;/g' /root/Desktop/ML-Projects/DB_SQL_GEN/samindu_live_fixed.sql
```

### 3. Create fixed wrapper file

```bash
echo "SET SESSION innodb_strict_mode=OFF;" > /root/Desktop/ML-Projects/DB_SQL_GEN/restore_wrapper_fixed.sql

echo "SET FOREIGN_KEY_CHECKS=0;" >> /root/Desktop/ML-Projects/DB_SQL_GEN/restore_wrapper_fixed.sql

cat /root/Desktop/ML-Projects/DB_SQL_GEN/samindu_live_fixed.sql >> /root/Desktop/ML-Projects/DB_SQL_GEN/restore_wrapper_fixed.sql

echo "SET FOREIGN_KEY_CHECKS=1;" >> /root/Desktop/ML-Projects/DB_SQL_GEN/restore_wrapper_fixed.sql
```

### 4. Restore fixed file

```bash
mysql -u root -p -e "DROP DATABASE IF EXISTS samindu_live; CREATE DATABASE samindu_live CHARACTER SET latin1 COLLATE latin1_swedish_ci;"

mysql -u root -p samindu_live < /root/Desktop/ML-Projects/DB_SQL_GEN/restore_wrapper_fixed.sql > /root/Desktop/ML-Projects/DB_SQL_GEN/restore_output.log 2> /root/Desktop/ML-Projects/DB_SQL_GEN/restore_error.log
```

---

## Important Notes

Do **not** manually paste the full `CREATE TABLE` script into the MySQL terminal.

Use one of these methods instead:

```sql
SOURCE /full/path/file.sql;
```

or from Linux terminal:

```bash
mysql -u root -p database_name < file.sql
```

For this specific dump, do **not** use plain `SOURCE` without wrapper settings.

Always restore with:

```sql
SET SESSION innodb_strict_mode=OFF;
SET FOREIGN_KEY_CHECKS=0;
-- source file content here
SET FOREIGN_KEY_CHECKS=1;
```

---

## Reason for These Settings

### `SET FOREIGN_KEY_CHECKS=0`

Required because the dump has circular foreign key references:

```text
external_parties -> users
users -> external_parties
```

Without this setting, table creation can fail depending on table order.

### `SET SESSION innodb_strict_mode=OFF`

Required because `external_parties` may fail with:

```text
ERROR 1118 (42000): Row size too large (> 8126)
```

This allows MySQL to create the table even with large row definitions.

### `ROW_FORMAT=DYNAMIC`

Use this only if `innodb_strict_mode=OFF` is not enough. It helps InnoDB store large variable-length columns more safely.

---

## Final Verification Query

```bash
mysql -u root -p samindu_live -e "SHOW TABLES LIKE 'external_parties'; SHOW TABLES LIKE 'users'; SELECT COUNT(*) FROM external_parties; SELECT COUNT(*) FROM users;"
```
