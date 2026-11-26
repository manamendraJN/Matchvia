"""The launch list of areas (US-A03). Admins add more in the admin site."""

from django.db import migrations

LAUNCH_AREAS = [
    ("Malabe", "malabe"),
    ("Battaramulla", "battaramulla"),
    ("Athurugiriya", "athurugiriya"),
    ("Kaduwela", "kaduwela"),
    ("Kotte", "kotte"),
    ("Maharagama", "maharagama"),
    ("Nugegoda", "nugegoda"),
]


def add_areas(apps, schema_editor):
    Area = apps.get_model("venues", "Area")
    for position, (name, slug) in enumerate(LAUNCH_AREAS):
        Area.objects.get_or_create(slug=slug, defaults={"name": name, "position": position})


def remove_areas(apps, schema_editor):
    Area = apps.get_model("venues", "Area")
    Area.objects.filter(slug__in=[slug for _name, slug in LAUNCH_AREAS], venue__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("venues", "0001_initial")]

    operations = [migrations.RunPython(add_areas, remove_areas)]
