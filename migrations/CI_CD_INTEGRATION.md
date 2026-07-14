# CI/CD Integration Guide

## Integration with Your Deployment Pipeline

The `renumber_learner_ids.py` script is designed to be run as part of your application deployment.

## GitHub Actions Example

Add this to your workflow (e.g., `.github/workflows/deploy.yml`):

```yaml
- name: Apply database migrations
  run: |
    cd ${{ github.workspace }}
    python migrations/renumber_learner_ids.py lmpts.db
  env:
    DB_PATH: lmpts.db
```

## Docker Example

In your `Dockerfile`:

```dockerfile
# After copying files
COPY . /app
WORKDIR /app

# Run migrations before starting app
RUN python migrations/renumber_learner_ids.py lmpts.db

# Start application
CMD ["python", "main.py"]
```

Or in Docker Compose:

```yaml
services:
  app:
    build: .
    volumes:
      - ./lmpts.db:/app/lmpts.db
    environment:
      DB_PATH: /app/lmpts.db
    command: >
      sh -c "python migrations/renumber_learner_ids.py /app/lmpts.db &&
             python main.py"
```

## Shell Script Example

In your deployment script (e.g., `deploy.sh`):

```bash
#!/bin/bash
set -e

# Navigate to project
cd /path/to/learn_graph_project

# Apply migrations
echo "Applying database migrations..."
python migrations/renumber_learner_ids.py lmpts.db
if [ $? -ne 0 ]; then
    echo "Migration failed. Aborting deployment."
    exit 1
fi

# Start application
echo "Starting application..."
python main.py
```

## AWS Lambda Example

```python
# In your Lambda handler
import subprocess
import os

def lambda_handler(event, context):
    db_path = os.environ.get('DB_PATH', '/tmp/lmpts.db')
    
    # Apply migrations
    result = subprocess.run(
        ['python', 'migrations/renumber_learner_ids.py', db_path],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"Migration failed: {result.stderr}")
        return {'statusCode': 500, 'body': 'Migration failed'}
    
    # Continue with app logic
    # ...
```

## Kubernetes Example

In your deployment manifest:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: learn-graph-app
spec:
  template:
    spec:
      containers:
      - name: app
        image: learn-graph:latest
        env:
        - name: DB_PATH
          value: /data/lmpts.db
        lifecycle:
          postStart:
            exec:
              command:
              - /bin/sh
              - -c
              - python migrations/renumber_learner_ids.py /data/lmpts.db
        volumeMounts:
        - name: db
          mountPath: /data
      volumes:
      - name: db
        persistentVolumeClaim:
          claimName: db-pvc
```

## Benefits for CI/CD

1. **Automated**: Runs automatically on each deployment
2. **Safe**: Idempotent - running multiple times is safe
3. **Verified**: Built-in verification catches issues early
4. **Logged**: Detailed logs for audit trail
5. **Reversible**: Backup created automatically before changes

## Exit Codes

- `0`: Success (migration applied or already migrated)
- `1`: Error (database not found, migration failed, etc.)

Use these in your CI/CD scripts:

```bash
python migrations/renumber_learner_ids.py lmpts.db
if [ $? -eq 0 ]; then
    echo "Migration successful"
else
    echo "Migration failed"
    exit 1
fi
```

## Dry-Run in Pre-Deployment

To verify changes before deploying to production:

```bash
# In staging/QA environment
python migrations/renumber_learner_ids.py staging.db --dry-run

# Review output, then deploy to production
python migrations/renumber_learner_ids.py production.db
```

## Monitoring and Alerts

Check logs after deployment:

```bash
# View latest migration log
tail -20 migrations_logs/renumber_learner_ids_*.log

# Verify in database
sqlite3 lmpts.db \
  "SELECT COUNT(*), MIN(learner_id), MAX(learner_id) FROM learners;"

# Check for any issues
grep -i "error\|failed" migrations_logs/renumber_learner_ids_*.log
```

## Zero-Downtime Deployment

The migration can run while the app is still handling requests:

1. Start migration (reads only during mapping phase)
2. Brief write-lock during transaction (milliseconds)
3. App can serve requests throughout

No changes to app code needed - the migration handles everything.

## Questions?

See [README.md](README.md) for detailed documentation.
