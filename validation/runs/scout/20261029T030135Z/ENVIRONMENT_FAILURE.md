# Not a Scout result

All 10 items are ERROR with `SSLCertVerificationError`. The local Norton Web/Mail Shield intercepts TLS and re-signs `ebi.ac.uk` with its own root certificate. That root is in the Windows certificate store (curl succeeds) but not in the Python `certifi` bundle, so `requests` rejects the connection.

TLS verification was not disabled. The run is kept as a preserved failed attempt, per the protocol rule that errors are never dropped. It says nothing about Scout's correctness.
