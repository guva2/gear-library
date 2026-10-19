from django.db import migrations

# Re-creates the foreign key from memberships to the inventory, under its existing name,
# with the given ON DELETE action. The name ends in a hash, so it is looked up in
# pg_constraint.
REPLACE_INVENTORY_FOREIGN_KEY = """
DO $$
DECLARE
    fk_name name;
BEGIN
    SELECT conname INTO STRICT fk_name
    FROM pg_constraint
    WHERE contype = 'f'
      AND conrelid = 'gear_library_membership'::regclass
      AND confrelid = 'gear_library_inventory'::regclass;
    EXECUTE format(
        'ALTER TABLE gear_library_membership DROP CONSTRAINT %I, ADD CONSTRAINT %I'
        ' FOREIGN KEY (inventory_id) REFERENCES gear_library_inventory (id)'
        ' ON DELETE {action} DEFERRABLE INITIALLY DEFERRED',
        fk_name, fk_name
    );
END
$$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('gear_library', '0003_inventories'),
    ]

    operations = [
        migrations.RunSQL(
            REPLACE_INVENTORY_FOREIGN_KEY.format(action="CASCADE"),
            reverse_sql=REPLACE_INVENTORY_FOREIGN_KEY.format(action="NO ACTION"),
        ),
    ]
