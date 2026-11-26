"""Business logic for pricing: peak periods and the price for a court at a start time.

Services own the transaction; views stay thin. Cross-app calls go through the other
app's services.py (CLAUDE.md "Code conventions")."""
