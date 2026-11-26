"""Enable the btree_gist extension.

The no-double-booking exclusion constraint (data-model 4.1, CLAUDE.md rule 1) mixes an
equality test on the court with a range overlap, which needs btree_gist. The first bookings
migration depends on this one.

btree_gist is a trusted extension (PostgreSQL 13+), so the database owner can create it
without superuser rights.
"""

from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [BtreeGistExtension()]
