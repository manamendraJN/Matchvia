"""Weekly series stay inside one venue (data-model 6.3).

Fixed DDL, no user input. A series can't use another venue's court or customer, and a booking
can't belong to another venue's series. MATCH SIMPLE skips the booking check when series_id is
NULL (ordinary bookings).
"""

from django.db import migrations

CONSTRAINTS = [
    ("bookings_recurringseries", "series_court_same_venue",
     "(court_id, venue_id) REFERENCES venues_court (id, venue_id)"),
    ("bookings_recurringseries", "series_customer_same_venue",
     "(venue_customer_id, venue_id) REFERENCES venues_venuecustomer (id, venue_id)"),
    ("bookings_booking", "booking_series_same_venue",
     "(series_id, venue_id) REFERENCES bookings_recurringseries (id, venue_id)"),
]


class Migration(migrations.Migration):
    dependencies = [("bookings", "0004_recurring_series")]

    operations = [
        migrations.RunSQL(
            sql=f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY {target};",
            reverse_sql=f"ALTER TABLE {table} DROP CONSTRAINT {name};",
        )
        for table, name, target in CONSTRAINTS
    ]
