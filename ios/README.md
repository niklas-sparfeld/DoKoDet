# CardEventProbe iOS client

CardEventProbe captures evidence on iOS and sends accepted evidence packages to the local
backend.

## First hop

From the repository root:

- Owned app source: `ios/CardEventProbe/`.
- Swift Package source: the package target sources listed in `ios/Package.swift`.
- Tests: `ios/CardEventProbeTests/`.
- Local pipeline client: `ios/Integration/`.
- Upstream boundary: camera frames and CardEventNet event proposals enter the capture workflow.
- Downstream boundary: the client stores evidence packages and sends them to the backend intake
  API.

Use the [repository documentation route](../README.md#documentation-route) for architecture,
work state, shared contracts, and lifecycle rules. Use the [data lifecycle](../docs/Data_Lifecycle.md)
and [repository intake contract](../docs/Repository_Intake_Contract.md) for package state and
intake requirements.

## Verification

Run the Swift Package checks from the repository root:

```bash
mise exec -- swift build --package-path ios
mise exec -- swift test --package-path ios
```

These checks cover the package-compatible core and local pipeline client. They do not build the
iOS app target.

Build the app target separately with Xcode:

```bash
xcodebuild -project ios/CardEventProbe.xcodeproj \
  -scheme CardEventProbe \
  -sdk iphonesimulator \
  -configuration Debug \
  build
```
