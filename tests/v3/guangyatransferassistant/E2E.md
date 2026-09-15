# GuangYa Transfer Assistant E2E

This directory contains the real-environment test entrypoints for the GuangYa Transfer Assistant.

The GitHub workflow runs only on a self-hosted runner carrying these labels:

- `self-hosted`
- `linux`
- `guangya-e2e`

## Fixed test environment

- MoviePilot: `http://mp.odn.cc`
- GuangYa isolated test root: `/g-box`

The preflight performs no remote writes.

## Required GitHub repository secrets

Configure these in GitHub repository Settings -> Secrets and variables -> Actions:

- `MP_TEST_USERNAME`
- `MP_TEST_PASSWORD`
- `GY_TEST_GUANGYA_SHARE`
- `GY_TEST_XUNLEI_SHARE`
- `GY_TEST_MAGNET`
- `GY_TEST_ED2K`

Do not commit their values.

Future destructive E2E stages must refuse to run unless every target path is inside `/g-box`.
