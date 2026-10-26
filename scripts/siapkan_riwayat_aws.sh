#!/usr/bin/env bash
# Sekali jalan per lingkungan: tabel DynamoDB untuk riwayat chat dan task role
# yang hanya boleh membaca dan menulis tabel itu (#70). Aman diulang, sumber yang
# sudah ada dilewati. Sesudahnya jalankan deploy_aws.sh seperti biasa. Deploy
# memasang role dan RIWAYAT_TABEL sendiri bila role-nya ditemukan.
#
# Pemakaian:
#   AWS_PROFILE=olist scripts/siapkan_riwayat_aws.sh                  # produksi
#   AWS_PROFILE=olist TARGET=staging scripts/siapkan_riwayat_aws.sh   # staging
#
# Bongkar:
#   aws iam delete-role-policy --role-name <role> --policy-name riwayat-dynamodb
#   aws iam delete-role --role-name <role>
#   aws dynamodb delete-table --table-name <tabel>

set -euo pipefail

REGION="${AWS_REGION:-ap-southeast-1}"
TARGET="${TARGET:-production}"
case "${TARGET}" in
  production) TABEL="olist-riwayat"; ROLE="olist-api-task" ;;
  staging) TABEL="olist-riwayat-staging"; ROLE="olist-api-staging-task" ;;
  *) echo "TARGET harus production atau staging" >&2; exit 1 ;;
esac
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
TABEL_ARN="arn:aws:dynamodb:${REGION}:${ACCOUNT}:table/${TABEL}"

if aws dynamodb describe-table --region "${REGION}" --table-name "${TABEL}" >/dev/null 2>&1; then
  echo "Tabel ${TABEL} sudah ada"
else
  # Bayar per permintaan: tanpa biaya tetap, cocok untuk trafik demo.
  aws dynamodb create-table --region "${REGION}" --table-name "${TABEL}" \
    --attribute-definitions AttributeName=PK,AttributeType=S AttributeName=SK,AttributeType=S \
    --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST --tags Key=project,Value=olist \
    --query 'TableDescription.TableStatus' --output text
  aws dynamodb wait table-exists --region "${REGION}" --table-name "${TABEL}"
fi
# Atribut ttl diisi DynamoDBSaver (umur sesi RIWAYAT_UMUR_JAM).
if ! aws dynamodb describe-time-to-live --region "${REGION}" --table-name "${TABEL}" \
    --query 'TimeToLiveDescription.TimeToLiveStatus' --output text | grep -q ENABLED; then
  aws dynamodb update-time-to-live --region "${REGION}" --table-name "${TABEL}" \
    --time-to-live-specification Enabled=true,AttributeName=ttl \
    --query 'TimeToLiveSpecification.Enabled' --output text
fi

if aws iam get-role --role-name "${ROLE}" >/dev/null 2>&1; then
  echo "Role ${ROLE} sudah ada"
else
  aws iam create-role --role-name "${ROLE}" \
    --description "Task role ${TARGET} OLIST, hanya tabel riwayat chat" \
    --assume-role-policy-document "$(cat <<JSON
{"Version": "2012-10-17",
 "Statement": [{"Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"aws:SourceAccount": "${ACCOUNT}"}}}]}
JSON
)" --query 'Role.Arn' --output text
fi
# Hanya tabel lingkungan ini. Produksi tidak bisa membaca riwayat staging.
aws iam put-role-policy --role-name "${ROLE}" --policy-name riwayat-dynamodb \
  --policy-document "$(cat <<JSON
{"Version": "2012-10-17",
 "Statement": [{"Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem",
                           "dynamodb:Query", "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem"],
                "Resource": "${TABEL_ARN}"}]}
JSON
)"
echo "Siap: tabel ${TABEL}, role ${ROLE}. Lanjutkan dengan TARGET=${TARGET} scripts/deploy_aws.sh"
