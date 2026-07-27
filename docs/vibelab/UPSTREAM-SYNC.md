# Synchronising with OpenSail

`main` is the stable VibeLab branch and `upstream` points to
`https://github.com/TesslateAI/OpenSail.git`.

```bash
git fetch upstream
git checkout main
git merge upstream/main
```

Review conflicts deliberately, especially in visible branding and marketplace
seed files. Do not rewrite shared history or automate upstream merges.
