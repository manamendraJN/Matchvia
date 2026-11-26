"""Business logic for adminpanel: django admin customisation for platform admins.

Services own the transaction; views stay thin. Cross-app calls go through the other
app's services.py (CLAUDE.md "Code conventions")."""
