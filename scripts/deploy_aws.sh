#!/usr/bin/env bash
# Build image dari commit saat ini, push ke ECR, lalu perbarui service
# ECS Express Mode. Tidak ada ID akun atau kunci di berkas ini. Semuanya dibaca
# dari profil AWS CLI saat dijalankan.
#
# Pemakaian:
#   AWS_PROFILE=olist scripts/deploy_aws.sh                    # produksi
#   AWS_PROFILE=olist TARGET=staging scripts/deploy_aws.sh     # staging
#
# Staging (olist-api-staging) memakai kunci akses dan akun demo sendiri di
# /olist/staging/, dan kunci OpenAI, Qdrant, Langfuse yang sama dengan produksi.
# Service staging dibuat otomatis pada deploy pertama. Uji keamanan dan red team
# promptfoo dijalankan ke staging, bukan ke produksi.
#
# Prasyarat sekali jalan (sudah dibuat 18 Oktober 2026): parameter SSM
# /olist/* berisi kunci layanan, repository ECR
# olist-insight-assistant, role ecsTaskExecutionRole dan
# ecsInfrastructureRoleForExpressServices, dan service Express olist-api di
# cluster default.

set -euo pipefail

REGION="${AWS_REGION:-ap-southeast-1}"
REPO="olist-insight-assistant"
TARGET="${TARGET:-production}"
case "${TARGET}" in
  production) SERVICE="olist-api"; PREFIX_AKSES="/olist"; TABEL="olist-riwayat"; ROLE="olist-api-task" ;;
  staging) SERVICE="olist-api-staging"; PREFIX_AKSES="/olist/staging"; TABEL="olist-riwayat-staging"
    ROLE="olist-api-staging-task" ;;
  *) echo "TARGET harus production atau staging" >&2; exit 1 ;;
esac
# Kunci yang berbeda per lingkungan. Sisanya dipakai bersama.
KUNCI_AKSES="API_ACCESS_KEY AUTH_SECRET DEMO_USERS"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree belum bersih. Commit dulu supaya tag image sama dengan commit." >&2
  exit 1
fi

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

# Rahasia keamanan wajib ada sebelum build. Tanpa ini container produksi menolak
# start (periksa_konfigurasi), jadi lebih baik gagal di sini (audit 25 Okt, S02).
for name in ${KUNCI_AKSES}; do
  if ! aws ssm describe-parameters --region "${REGION}" \
      --parameter-filters "Key=Name,Values=${PREFIX_AKSES}/${name}" \
      --query 'length(Parameters)' --output text | grep -q '^1$'; then
    echo "Parameter SSM ${PREFIX_AKSES}/${name} tidak ada. Deploy dibatalkan." >&2
    exit 1
  fi
done
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
#
# Semua nama dicek dalam satu panggilan. Dulu setiap nama dicek sendiri dengan
# `if aws ... | grep`, sehingga galat jaringan dibaca sebagai "tidak ada" dan kunci
# OpenAI diam-diam tertinggal dari task staging (26 Okt). Kini galat menghentikan
# deploy (set -e), dan kunci wajib yang tidak ada membatalkan deploy.
WAJIB="OPENAI_API_KEY QDRANT_URL QDRANT_API_KEY ${KUNCI_AKSES}"
OPSIONAL="LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_HOST"
path_ssm() {
  if [[ " ${KUNCI_AKSES} " == *" $1 "* ]]; then echo "${PREFIX_AKSES}/$1"; else echo "/olist/$1"; fi
}
SEMUA=""
for name in ${WAJIB} ${OPSIONAL}; do SEMUA="${SEMUA:+${SEMUA},}$(path_ssm "${name}")"; done
ADA="$(aws ssm describe-parameters --region "${REGION}" \
  --parameter-filters "Key=Name,Values=${SEMUA}" --query 'Parameters[].Name' --output text)"
ADA=" $(echo "${ADA}" | tr '\t\n' '  ') "
SECRETS=""
for name in ${WAJIB} ${OPSIONAL}; do
  path="$(path_ssm "${name}")"
  if [[ "${ADA}" != *" ${path} "* ]]; then
    if [[ " ${WAJIB} " == *" ${name} "* ]]; then
      echo "Parameter SSM wajib ${path} tidak ada. Deploy dibatalkan." >&2
      exit 1
    fi
    echo "Parameter opsional ${path} tidak ada, dilewati" >&2
    continue
  fi
  SECRETS="${SECRETS:+${SECRETS},}{\"name\": \"${name}\", \"valueFrom\": \"arn:aws:ssm:${REGION}:${ACCOUNT}:parameter${path}\"}"
done

# Riwayat chat di DynamoDB bila tabel dan role dari siapkan_riwayat_aws.sh sudah ada
# (#70). Tanpa itu riwayat di memori dan hilang setiap task diganti.
RIWAYAT_ENV=""
TASK_ROLE=()
if aws iam get-role --role-name "${ROLE}" >/dev/null 2>&1; then
  RIWAYAT_ENV=", {\"name\": \"RIWAYAT_TABEL\", \"value\": \"${TABEL}\"}"
  TASK_ROLE=(--task-role-arn "arn:aws:iam::${ACCOUNT}:role/${ROLE}")
  echo "Riwayat chat disimpan di DynamoDB ${TABEL}"
else
  echo "Role ${ROLE} belum ada, riwayat chat di memori. Jalankan siapkan_riwayat_aws.sh." >&2
fi

# Kuota dinaikkan dari bawaan (60 per klien, 30 per akun) setelah uji beban 26 Okt:
# satu task melayani 40 pengguna serentak dengan p95 23 detik. Semua pengguna
# Streamlit Cloud datang dari satu alamat, dan penguji bisa berbagi akun demo.
CONTAINER="$(cat <<JSON
{"image": "${IMAGE}", "containerPort": 8000,
 "environment": [{"name": "APP_ENV", "value": "production"},
                 {"name": "LANGFUSE_TRACING_ENVIRONMENT", "value": "${TARGET}"},
                 {"name": "RATE_LIMIT_PER_CLIENT", "value": "120"},
                 {"name": "RATE_LIMIT_PER_ACCOUNT", "value": "60"}${RIWAYAT_ENV}],
 "secrets": [${SECRETS}]}
JSON
)"

SERVICE_ARN="arn:aws:ecs:${REGION}:${ACCOUNT}:service/default/${SERVICE}"
if aws ecs describe-express-gateway-service --region "${REGION}" --service-arn "${SERVICE_ARN}" \
    --query 'service.status.statusCode' --output text 2>/dev/null | grep -q ACTIVE; then
  aws ecs update-express-gateway-service \
    --region "${REGION}" \
    --service-arn "${SERVICE_ARN}" \
    ${TASK_ROLE[@]+"${TASK_ROLE[@]}"} \
    --primary-container "${CONTAINER}" \
    --query 'service.status.statusCode' --output text
else
  echo "Service ${SERVICE} belum ada, dibuat sekarang (ukuran sama dengan produksi)"
  aws ecs create-express-gateway-service \
    --region "${REGION}" \
    --cluster default \
    --service-name "${SERVICE}" \
    --execution-role-arn "arn:aws:iam::${ACCOUNT}:role/ecsTaskExecutionRole" \
    ${TASK_ROLE[@]+"${TASK_ROLE[@]}"} \
    --infrastructure-role-arn "arn:aws:iam::${ACCOUNT}:role/ecsInfrastructureRoleForExpressServices" \
    --health-check-path /health \
    --cpu 256 --memory 1024 --cpu-architecture ARM64 \
    --scaling-target '{"minTaskCount": 1, "maxTaskCount": 1, "autoScalingMetric": "AVERAGE_CPU", "autoScalingTargetValue": 60}' \
    --primary-container "${CONTAINER}" \
    --query 'service.status.statusCode' --output text
fi

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
    echo "Deploy ${TAG} aktif di ${SERVICE}."
    aws ecs describe-express-gateway-service --region "${REGION}" --service-arn "${SERVICE_ARN}" \
      --query 'service.activeConfigurations[0].ingressPaths[0].endpoint' --output text
    exit 0
  fi
  [[ "${state}" == "FAILED" ]] && break
done
echo "Deploy ${TAG} GAGAL. Rollout ${state:-?}, task berjalan memakai: ${running:-?}" >&2
aws ecs describe-services --region "${REGION}" --cluster default --services "${SERVICE}" \
  --query 'services[0].events[:5].message' --output text >&2
exit 1
