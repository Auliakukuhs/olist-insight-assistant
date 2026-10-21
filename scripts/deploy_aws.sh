#!/usr/bin/env bash
# Build image dari commit saat ini, push ke ECR, lalu perbarui service
# ECS Express Mode. Tidak ada ID akun atau kunci di berkas ini. Semuanya dibaca
# dari profil AWS CLI saat dijalankan.
#
# Pemakaian:
#   AWS_PROFILE=olist scripts/deploy_aws.sh
#
# Prasyarat sekali jalan (sudah dibuat 18 Oktober 2026): parameter SSM
# /olist/* berisi kunci layanan, repository ECR
# olist-insight-assistant, role ecsTaskExecutionRole dan
# ecsInfrastructureRoleForExpressServices, dan service Express olist-api di
# cluster default.

set -euo pipefail

REGION="${AWS_REGION:-ap-southeast-1}"
REPO="olist-insight-assistant"
SERVICE="olist-api"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree belum bersih. Commit dulu supaya tag image sama dengan commit." >&2
  exit 1
fi

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
TAG="$(git rev-parse --short HEAD)"
IMAGE="${REGISTRY}/${REPO}:${TAG}"

echo "Build ${REPO}:${TAG} untuk linux/arm64"
docker build --platform linux/arm64 -t "${IMAGE}" .

aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"
for attempt in 1 2 3; do
  docker push "${IMAGE}" && break
  echo "Push gagal (percobaan ${attempt}), ulangi" >&2
  sleep 5
done

# Kunci layanan dibaca ECS dari SSM Parameter Store (SecureString) saat task
# start, lalu disuntik sebagai environment. Nilainya tidak pernah masuk image
# maupun berkas ini. Execution role hanya boleh membaca parameter /olist/*.
SECRETS=""
for name in OPENAI_API_KEY QDRANT_URL QDRANT_API_KEY LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_HOST API_ACCESS_KEY AUTH_SECRET DEMO_USERS; do
  arn="arn:aws:ssm:${REGION}:${ACCOUNT}:parameter/olist/${name}"
  if aws ssm describe-parameters --region "${REGION}" \
      --parameter-filters "Key=Name,Values=/olist/${name}" \
      --query 'length(Parameters)' --output text | grep -q '^1$'; then
    SECRETS="${SECRETS:+${SECRETS},}{\"name\": \"${name}\", \"valueFrom\": \"${arn}\"}"
  fi
done

CONTAINER="$(cat <<JSON
{"image": "${IMAGE}", "containerPort": 8000,
 "environment": [{"name": "APP_ENV", "value": "production"}],
 "secrets": [${SECRETS}]}
JSON
)"

aws ecs update-express-gateway-service \
  --region "${REGION}" \
  --service-arn "arn:aws:ecs:${REGION}:${ACCOUNT}:service/default/${SERVICE}" \
  --primary-container "${CONTAINER}" \
  --query 'service.status.statusCode' --output text

echo "Deploy ${TAG} dikirim. Pantau dengan:"
echo "  aws ecs describe-services --cluster default --services ${SERVICE} --query 'services[0].events[:3].message'"
