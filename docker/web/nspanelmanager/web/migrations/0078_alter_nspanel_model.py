from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('web', '0077_remove_horizontal_mirrored'),
    ]

    operations = [
        migrations.AlterField(
            model_name='nspanel',
            name='model',
            field=models.CharField(choices=[('sonoff', 'Sonoff'), ('custom', 'Custom')], max_length=32),
        ),
    ]
