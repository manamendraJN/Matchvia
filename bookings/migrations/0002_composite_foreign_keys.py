"""A booking can never point at another venue's court or customer (data-model 6.3).

Django can't declare composite foreign keys yet, so they are added here with fixed DDL (no user
input). They reference the UNIQUE (id, venue_id) constraints on Court and VenueCustomer. MATCH
SIMPLE (the default) skips the check when venue_customer_id is NULL (blocks and walk-ins).
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("bookings", "0001_initial")]

    operations = [
        migrations.RunSQL(
            sql=(
                "ALTER TABLE bookings_booking ADD CONSTRAINT booking_court_same_venue "
                "FOREIGN KEY (court_id, venue_id) REFERENCES venues_court (id, venue_id);"
            ),
            reverse_sql="ALTER TABLE bookings_booking DROP CONSTRAINT booking_court_same_venue;",
        ),
        migrations.RunSQL(
            sql=(
                "ALTER TABLE bookings_booking ADD CONSTRAINT booking_customer_same_venue "
                "FOREIGN KEY (venue_customer_id, venue_id) "
                "REFERENCES venues_venuecustomer (id, venue_id);"
            ),
            reverse_sql="ALTER TABLE bookings_booking DROP CONSTRAINT booking_customer_same_venue;",
        ),
    ]
