# Release Notes Template

## Highlights

- 

## Install Or Update

```bash
git pull
./scripts/bootstrap_local.sh
make demo
make smoke
```

## Verification

- `make verify`
- `python3 -m unittest discover -s tests`
- `cd app && swift build`

## Known Limitations

- 

## Privacy Notes

- External sources remain read-only by default.
- Cloud providers remain opt-in.
- Demo data is synthetic.
