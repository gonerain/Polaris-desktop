# Linux x86-64 bundle

`dependencies.lock.json` fixes the Python 3.10 Linux x86-64 wheel filenames and SHA-256 values. Obtain those exact wheels from the trusted package index and verify their digests against the lock before use. Install them to a fresh temporary directory with the project Python and no dependency resolution or network access:

```sh
python3.10 -m pip install --no-index --no-deps --no-compile --target /tmp/feishu-deps /path/to/locked-wheels/*.whl
python3.10 next/plugins/feishu/scripts/build_bundle.py --dependencies /tmp/feishu-deps --wheels /path/to/locked-wheels --output /path/to/new-bundle
```

The builder verifies every locked wheel, installed version, wheel file content and the normalized dependency tree. It copies the component and dependencies into a new self-contained directory. The output includes original third-party licenses and SDK notices in `vendor/*.dist-info`. Native dependencies are specific to Linux x86-64 and this Python version; build and test separate locks for other targets. Do not install or run directly from a temporary output directory: the platform retains the component directory path across restarts.
