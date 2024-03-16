# Backup strategy

```
tar -H posix -cvf some.tar files1

gpg --compress-algo none -o some.tar.gpg -c some.tar
```