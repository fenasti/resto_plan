# Hand-written (not autodetected) to avoid Django's rename-heuristic
# ambiguity between the old CharFields and the new FK fields sharing
# similar names — these explicit RemoveField/RenameField operations
# guarantee the data populated by 0004 is preserved, not dropped.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordering', '0004_migrate_category_supplier_to_fk'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='purchaseitem',
            name='category',
        ),
        migrations.RemoveField(
            model_name='purchaseitem',
            name='supplier',
        ),
        migrations.RenameField(
            model_name='purchaseitem',
            old_name='category_fk',
            new_name='category',
        ),
        migrations.RenameField(
            model_name='purchaseitem',
            old_name='supplier_fk',
            new_name='supplier',
        ),
        migrations.AlterField(
            model_name='purchaseitem',
            name='supplier',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='purchase_items', to='ordering.supplier',
                help_text='Who you buy this from — lets an order be split and exported per supplier.',
            ),
        ),
    ]
