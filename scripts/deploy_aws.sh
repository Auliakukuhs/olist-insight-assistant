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
# `docker push ... && break` di dalam loop tidak dihentikan `set -e`, jadi status
# berhasil dicatat sendiri. Tanpa ini, tiga push gagal tetap lanjut ke update
# service, ECS gagal menarik image, lalu diam-diam kembali ke versi lama.
pushed=0
for attempt in 1 2 3; do
  if docker push "${IMAGE}"; then
    pushed=1
    break
  fi
  echo "Push gagal (percobaan ${attempt}), ulangi" >&2
  sleep 5
done
if [[ "${pushed}" != 1 ]]; then
  echo "Push ${TAG} gagal tiga kali. Service tidak diubah." >&2
  exit 1
fi
aws ecr describe-images --region "${REGION}" --repository-name "${REPO}" \
  --image-ids "imageTag=${TAG}" --query 'imageDetails[0].imageDigest' --output text >/dev/null

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

# Tunggu rollout selesai, lalu pastikan task yang berjalan memakai image ini.
# Rollout yang gagal di-rollback otomatis oleh ECS, jadi "COMPLETED" saja belum
# cukup sebagai bukti. Tepat sesudah update, status yang terbaca juga bisa masih
# milik deployment lama, jadi image task ikut dicek di setiap putaran.
echo "Menunggu rollout ${TAG}"
for _ in $(seq 1 60); do
  sleep 15
  state="$(aws ecs describe-services --region "${REGION}" --cluster default --services "${SERVICE}" \
    --query 'services[0].deployments[?status==`PRIMARY`]|[0].rolloutState' --output text)"
  tasks="$(aws ecs list-tasks --region "${REGION}" --cluster default --service-name "${SERVICE}" \
    --desired-status RUNNING --query 'taskArns' --output text)"
  [[ -z "${tasks}" || "${tasks}" == "None" ]] && continue
  running="$(aws ecs describe-tasks --region "${REGION}" --cluster default --tasks ${tasks} \
    --query 'tasks[].containers[0].image' --output text)"
  if [[ "${state}" == "COMPLETED" && "${running}" == "${IMAGE}" ]]; then
    echo "Deploy ${TAG} aktif."
    exit 0
  fi
  [[ "${state}" == "FAILED" ]] && break
done
echo "Deploy ${TAG} GAGAL. Rollout ${state:-?}, task berjalan memakai: ${running:-?}" >&2
aws ecs describe-services --region "${REGION}" --cluster default --services "${SERVICE}" \
  --query 'services[0].events[:5].message' --output text >&2
exit 1
