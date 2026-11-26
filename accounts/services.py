"""Business logic for accounts: users, phone OTP sign-in, consent and account deletion.

Services own the transaction; views stay thin. Cross-app calls go through the other
app's services.py (CLAUDE.md "Code conventions")."""
