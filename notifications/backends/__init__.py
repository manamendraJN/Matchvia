"""SMS gateway backends. The worker loads the one named by settings.SMS_BACKEND.

console  development: prints each SMS to the worker's terminal
locmem   tests: records messages in memory
textlk   production: Text.lk HTTP API (implemented in C7/S08, decision D4)
"""
