{{/*
Chart name
*/}}
{{- define "miu-bot.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fullname (same as name for this chart -- no release-name prefix needed)
*/}}
{{- define "miu-bot.fullname" -}}
{{- default .Chart.Name .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "miu-bot.labels" -}}
app.kubernetes.io/name: {{ include "miu-bot.name" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: dataplanelabs
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end }}

{{/*
Gateway selector labels
*/}}
{{- define "miu-bot.gateway.selectorLabels" -}}
app: miubot-gateway
app.kubernetes.io/name: {{ include "miu-bot.name" . }}
app.kubernetes.io/component: gateway
{{- end }}

{{/*
Worker selector labels
*/}}
{{- define "miu-bot.worker.selectorLabels" -}}
app: miubot-worker
app.kubernetes.io/name: {{ include "miu-bot.name" . }}
app.kubernetes.io/component: worker
{{- end }}

{{/*
Container image with tag
*/}}
{{- define "miu-bot.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}
{{- end }}
