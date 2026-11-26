"""Business logic for bookings: free slots, bookings, blocks, recurring series and the audit trail.

Services own the transaction; views stay thin. Cross-app calls go through the other
app's services.py (CLAUDE.md "Code conventions")."""
