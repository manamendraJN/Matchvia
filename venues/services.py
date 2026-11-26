"""Business logic for venues: venues, courts, opening hours, settings, staff and customer book.

Services own the transaction; views stay thin. Cross-app calls go through the other
app's services.py (CLAUDE.md "Code conventions")."""
