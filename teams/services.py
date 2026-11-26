"""Business logic for teams: teams, members and invites.

Services own the transaction; views stay thin. Cross-app calls go through the other
app's services.py (CLAUDE.md "Code conventions")."""
