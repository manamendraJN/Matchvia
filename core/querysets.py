from django.db import models


class VenueOwnedQuerySet(models.QuerySet):
    """Every venue-owned table uses this, so scoping is one explicit filter (data-model 6.2).

    Views call ``Court.objects.for_venue(venue).get(pk=pk)``, never ``Court.objects.get(pk=pk)``:
    an id from another venue is simply not found.
    """

    def for_venue(self, venue):
        return self.filter(venue=venue)
