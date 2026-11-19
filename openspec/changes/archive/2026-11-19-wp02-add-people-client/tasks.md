## 1. HTTP client and lifecycle

- [x] 1.1 Declare the runtime dependency and implement typed responses, per-call timeouts, and HTTP error handling.
- [x] 1.2 Wire the client into the application lifespan and verify startup and shutdown without network calls.

## 2. Collecting reference data

- [x] 2.1 Collect the required responses concurrently and handle cancellation and multiple failures.
- [x] 2.2 Map service errors to the contract and cover the error responses without network access.

## 3. Verification and documentation

- [x] 3.1 Measure sequential and concurrent runs with a delayed fake and record the results in README.
- [x] 3.2 Run the targeted checks and `just check`, then validate the OpenSpec change.
