**DuckDB 2 refuses `register()` and running a relation on a cursor whose last result has unread rows; `fetchone()` leaves it so.**

Found when Where MPs Stand moved from DuckDB 1.5.6 to 2.0.0 (13 November 2026): `connection has an unfinished result
from execute()`. Only `register`, `create_function` and running a relation (`sql(...).fetchall()`) fail; `execute`,
`executemany` and `unregister` are fine. The shared connection wrapper gives each thread one long-lived cursor, so a
single-row look-up anywhere breaks a later registration on the same thread. The fix is in the wrapper: call
`complete()` before those calls. The tests caught one path of about twenty-five: don't trust a green suite alone
after a major version of a library; probe the behaviour that changed.
