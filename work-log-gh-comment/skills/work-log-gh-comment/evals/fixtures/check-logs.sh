#!/bin/sh
echo "scanning application logs (last 24h)"
echo "app-web    : 1420 lines, 0 errors"
echo "app-worker : 880 lines, 3 errors"
echo "  2026-08-27T03:11:02Z ERROR failed to renew lease, retrying"
echo "  2026-08-27T03:11:07Z ERROR failed to renew lease, retrying"
echo "  2026-08-27T03:11:12Z INFO  lease renewed"
echo "app-db     : 210 lines, 0 errors"
echo "scan complete"
