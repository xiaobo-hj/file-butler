<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  AppstoreOutlined,
  CloudUploadOutlined,
  FileOutlined,
  FilePdfOutlined,
  FileSearchOutlined,
  FolderOpenOutlined,
  InboxOutlined,
  MessageOutlined,
  SearchOutlined,
  UploadOutlined,
} from '@ant-design/icons-vue'

const activePage = ref('overview')
const dashboard = ref(null)
const uploadPage = ref({ queue: [], hint: '' })
const suggestionsPage = ref({ suggestions: [], selectedSuggestion: null, summary: null })
const libraryPage = ref({
  summary: {
    totalFiles: '0',
    organizedFiles: '0',
    indexedFiles: '0',
    folders: '0',
    totalSize: '0 KB',
  },
  files: [],
  filters: { folders: [], statuses: [] },
})
const isLoading = ref(false)
const isUploading = ref(false)
const isDeciding = ref(false)
const loadError = ref('')
const decisionNotice = ref('')
const fileInput = ref(null)
const librarySearch = ref('')
const libraryStatusFilter = ref('all')
const libraryFolderFilter = ref('all')

const navItems = [
  { key: 'overview', label: '总览', icon: AppstoreOutlined },
  { key: 'upload', label: '上传文件', icon: CloudUploadOutlined },
  { key: 'suggestions', label: '整理建议', icon: FileSearchOutlined },
  { key: 'library', label: '文件库', icon: FolderOpenOutlined },
  { key: 'qa', label: '知识库问答', icon: MessageOutlined },
]

const pageMeta = computed(() => {
  if (activePage.value === 'upload') {
    return {
      title: '上传文件',
      subtitle: 'Agent 会先分析文件内容并生成整理建议，用户确认前不会修改任何文件。',
    }
  }
  if (activePage.value === 'suggestions') {
    return {
      title: '整理建议',
      subtitle: '以下操作只有在你确认后才会执行。FileButler 不会自动改动文件。',
    }
  }
  if (activePage.value === 'library') {
    return { title: '文件库', subtitle: '集中浏览已经整理和索引的个人文件。' }
  }
  if (activePage.value === 'qa') {
    return { title: '知识库问答', subtitle: '向你的个人资料库提问，并查看引用文件。' }
  }
  return {
    title: 'FileButler 个人文件管家',
    subtitle: '把杂乱文件整理成可搜索、可问答、可维护的个人资料库',
  }
})

const overviewModel = computed(
  () =>
    dashboard.value ?? {
      metrics: [],
      suggestions: [],
      activities: [],
      knowledgePrompt: {
        title: '知识库暂无可用数据',
        description: '上传并确认文件后，这里会显示知识库状态。',
        actionLabel: '上传文件',
      },
    },
)

const selectedSuggestionIsPending = computed(
  () => suggestionsPage.value.selectedSuggestion?.rawStatus === 'pending',
)

const hasPendingSuggestions = computed(
  () => suggestionsPage.value.suggestions.some((item) => item.rawStatus === 'pending'),
)

const filteredLibraryFiles = computed(() => {
  const query = librarySearch.value.trim().toLowerCase()
  return libraryPage.value.files.filter((file) => {
    const matchesQuery =
      !query ||
      [file.fileName, file.folder, file.currentPath, file.summary, ...file.tags]
        .join(' ')
        .toLowerCase()
        .includes(query)
    const matchesStatus =
      libraryStatusFilter.value === 'all' || file.rawStatus === libraryStatusFilter.value
    const matchesFolder =
      libraryFolderFilter.value === 'all' || file.folder === libraryFolderFilter.value
    return matchesQuery && matchesStatus && matchesFolder
  })
})

async function loadCurrentPage() {
  isLoading.value = true
  loadError.value = ''

  try {
    if (activePage.value === 'overview') {
      dashboard.value = await fetchJson('/api/dashboard/overview')
    } else if (activePage.value === 'upload') {
      uploadPage.value = await fetchJson('/api/uploads')
    } else if (activePage.value === 'suggestions') {
      suggestionsPage.value = await fetchJson('/api/suggestions')
    } else if (activePage.value === 'library') {
      libraryPage.value = await fetchJson('/api/library')
    }
  } catch (error) {
    loadError.value = '后端接口暂不可用，请先启动后端服务。'
  } finally {
    isLoading.value = false
  }
}

async function fetchJson(url, options) {
  const response = await fetch(url, options)
  if (!response.ok) {
    throw new Error(`Request failed with ${response.status}`)
  }
  return response.json()
}

function switchPage(pageKey) {
  activePage.value = pageKey
  decisionNotice.value = ''
  loadCurrentPage()
}

function openFilePicker() {
  fileInput.value?.click()
}

async function registerSelectedFiles(event) {
  const files = Array.from(event.target.files ?? [])
  event.target.value = ''
  if (!files.length) {
    return
  }

  isUploading.value = true
  loadError.value = ''
  try {
    for (const file of files) {
      await fetchJson('/api/uploads', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_name: file.name,
          content_base64: await fileToBase64(file),
          mime_type: file.type || null,
        }),
      })
    }
    activePage.value = 'suggestions'
    await loadCurrentPage()
  } catch (error) {
    loadError.value = '上传或生成建议失败，请检查后端服务和模型配置。'
  } finally {
    isUploading.value = false
  }
}

async function decideSuggestion(decision) {
  const selected = suggestionsPage.value.selectedSuggestion
  if (!selected) {
    return
  }
  if (decision === 'approve' && selected.rawStatus !== 'pending') {
    decisionNotice.value = '这条建议已经处理过了。'
    return
  }

  isDeciding.value = true
  loadError.value = ''
  decisionNotice.value = ''
  try {
    await fetchJson(`/api/suggestions/${selected.id}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    })
    decisionNotice.value = decision === 'approve' ? '已确认并执行整理操作。' : '已更新建议状态。'
    await loadCurrentPage()
  } catch (error) {
    loadError.value = '处理建议失败，请检查后端日志后重试。'
  } finally {
    isDeciding.value = false
  }
}

async function approveAllSuggestions() {
  while (suggestionsPage.value.suggestions.some((item) => item.rawStatus === 'pending')) {
    const next = suggestionsPage.value.suggestions.find((item) => item.rawStatus === 'pending')
    if (!next) {
      return
    }
    await fetchJson(`/api/suggestions/${next.id}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision: 'approve' }),
    })
    await loadCurrentPage()
  }
}

async function fileToBase64(file) {
  const buffer = await file.arrayBuffer()
  const bytes = new Uint8Array(buffer)
  const chunkSize = 0x8000
  let binary = ''
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize))
  }
  return btoa(binary)
}

function libraryStatusColor(status) {
  if (status === 'indexed') {
    return 'success'
  }
  if (status === 'organized') {
    return 'processing'
  }
  if (status === 'error') {
    return 'error'
  }
  return 'default'
}

function formatLibraryUpdatedAt(value) {
  if (!value) {
    return '-'
  }
  return value.replace('T', ' ').replace('Z', '')
}

onMounted(loadCurrentPage)
</script>

<template>
  <a-config-provider
    :theme="{
      token: {
        colorPrimary: '#5B5FEF',
        borderRadius: 12,
        fontFamily:
          'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, PingFang SC, Microsoft YaHei, sans-serif',
      },
    }"
  >
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <h1>FileButler</h1>
          <p>Personal File Agent</p>
        </div>

        <nav class="nav-list" aria-label="主导航">
          <button
            v-for="item in navItems"
            :key="item.key"
            class="nav-item"
            :class="{ active: activePage === item.key }"
            type="button"
            @click="switchPage(item.key)"
          >
            <component :is="item.icon" />
            <span>{{ item.label }}</span>
          </button>
        </nav>

        <section class="safety-note">
          <strong>Human-in-the-loop</strong>
          <span>AI 只建议，不直接改文件</span>
          <span>所有操作需用户确认</span>
        </section>
      </aside>

      <main class="dashboard">
        <header class="page-header">
          <div>
            <h2>{{ pageMeta.title }}</h2>
            <p>{{ pageMeta.subtitle }}</p>
          </div>
          <div class="header-actions">
            <a-button
              v-if="activePage === 'suggestions'"
              type="primary"
              size="large"
              :disabled="!hasPendingSuggestions"
              @click="approveAllSuggestions"
            >
              全部同意
            </a-button>
            <a-button v-if="activePage === 'suggestions'" size="large">批量稍后</a-button>
            <a-button v-else type="primary" size="large" @click="switchPage('upload')">
              <template #icon><InboxOutlined /></template>
              上传新文件
            </a-button>
          </div>
        </header>

        <a-alert
          v-if="loadError"
          class="offline-alert"
          :message="loadError"
          type="warning"
          show-icon
        />
        <a-alert
          v-if="decisionNotice"
          class="offline-alert"
          :message="decisionNotice"
          type="success"
          show-icon
        />

        <a-spin :spinning="isLoading || isUploading || isDeciding">
          <section v-if="activePage === 'overview'" class="page-section">
            <section class="metric-grid">
              <a-card
                v-for="metric in overviewModel.metrics"
                :key="metric.key"
                class="metric-card"
              >
                <span class="metric-label">{{ metric.label }}</span>
                <strong class="metric-value">{{ metric.value }}</strong>
                <span class="metric-trend">{{ metric.trend }}</span>
              </a-card>
            </section>

            <section class="content-grid">
              <a-card class="panel-card suggestions-card">
                <template #title>最近整理建议</template>
                <template #extra>
                  <span class="panel-subtitle">确认后才会移动、重命名和打标签</span>
                </template>

                <a-empty v-if="!overviewModel.suggestions.length" description="暂无整理建议" />
                <div v-else class="suggestion-list">
                  <article
                    v-for="suggestion in overviewModel.suggestions"
                    :key="suggestion.id"
                    class="suggestion-row"
                  >
                    <div class="suggestion-copy">
                      <strong>{{ suggestion.fileName }}</strong>
                      <span>{{ suggestion.folder }}</span>
                    </div>
                    <div class="suggestion-tags">
                      <a-tag color="success">{{ suggestion.confidence }}</a-tag>
                      <a-tag color="warning">{{ suggestion.status }}</a-tag>
                    </div>
                  </article>
                </div>

                <a-button class="secondary-action" @click="switchPage('suggestions')">
                  查看全部建议
                </a-button>
              </a-card>

              <a-card class="panel-card activity-card">
                <template #title>最近整理记录</template>

                <a-empty v-if="!overviewModel.activities.length" description="暂无整理记录" />
                <a-timeline v-else class="activity-timeline">
                  <a-timeline-item v-for="activity in overviewModel.activities" :key="activity.id">
                    <span class="activity-time">{{ activity.time }}</span>
                    <strong>{{ activity.title }}</strong>
                    <p>{{ activity.description }}</p>
                  </a-timeline-item>
                </a-timeline>

                <section class="knowledge-callout">
                  <div>
                    <strong>{{ overviewModel.knowledgePrompt.title }}</strong>
                    <span>{{ overviewModel.knowledgePrompt.description }}</span>
                  </div>
                  <a-button type="primary" @click="switchPage('qa')">
                    {{ overviewModel.knowledgePrompt.actionLabel }}
                  </a-button>
                </section>
              </a-card>
            </section>
          </section>

          <section v-else-if="activePage === 'upload'" class="page-section upload-page">
            <a-card class="upload-drop-card">
              <button class="upload-drop-zone" type="button" @click="openFilePicker">
                <UploadOutlined />
                <strong>{{ isUploading ? '正在生成建议' : '选择文件上传' }}</strong>
                <span>Agent 会保存副本、分析内容并生成整理建议</span>
                <a-button type="primary" :loading="isUploading">选择文件</a-button>
              </button>
              <input
                ref="fileInput"
                class="hidden-file-input"
                type="file"
                multiple
                @change="registerSelectedFiles"
              />
            </a-card>

            <a-card class="upload-queue-card">
              <template #title>上传队列</template>

              <a-empty v-if="!uploadPage.queue.length" description="暂无上传文件" />
              <div v-else class="upload-queue">
                <article v-for="item in uploadPage.queue" :key="item.id" class="upload-row">
                  <div>
                    <strong>{{ item.fileName }}</strong>
                    <span>{{ item.sizeLabel }}</span>
                  </div>
                  <a-progress
                    class="upload-progress"
                    :percent="item.progress"
                    :show-info="false"
                    :status="item.tone === 'error' ? 'exception' : 'normal'"
                  />
                  <a-tag :color="item.tone === 'success' ? 'success' : item.tone === 'processing' ? 'processing' : 'default'">
                    {{ item.status }}
                  </a-tag>
                </article>
              </div>

              <div class="queue-hint">{{ uploadPage.hint }}</div>
            </a-card>
          </section>

          <section v-else-if="activePage === 'suggestions'" class="page-section suggestions-page">
            <a-card class="suggestion-list-panel">
              <template #title>建议列表</template>
              <a-empty v-if="!suggestionsPage.suggestions.length" description="暂无整理建议" />
              <div v-else class="compact-suggestion-list">
                <article
                  v-for="suggestion in suggestionsPage.suggestions"
                  :key="suggestion.id"
                  class="compact-suggestion-row"
                  :class="{ selected: suggestion.id === suggestionsPage.selectedSuggestion?.id }"
                >
                  <div>
                    <strong>{{ suggestion.fileName }}</strong>
                    <span>{{ suggestion.folder }}</span>
                  </div>
                  <a-tag color="success">{{ suggestion.confidence }}</a-tag>
                </article>
              </div>
              <section class="suggestion-summary">
                <strong>{{ suggestionsPage.summary?.label ?? '0 条建议待确认' }}</strong>
                <span>{{ suggestionsPage.summary?.description ?? '确认后才会执行整理操作' }}</span>
              </section>
            </a-card>

            <a-card class="suggestion-detail-panel">
              <a-empty
                v-if="!suggestionsPage.selectedSuggestion"
                description="暂无可确认的整理建议"
              />
              <template v-else>
                <div
                  class="human-loop-banner"
                  :class="{ completed: !selectedSuggestionIsPending }"
                >
                  {{
                    selectedSuggestionIsPending
                      ? '等待你确认：AI 只生成建议，不直接整理文件'
                      : `已处理：${suggestionsPage.selectedSuggestion.status}`
                  }}
                </div>
                <h3>{{ suggestionsPage.selectedSuggestion.fileName }}</h3>
                <dl class="detail-fields">
                  <div>
                    <dt>当前路径</dt>
                    <dd>{{ suggestionsPage.selectedSuggestion.currentPath }}</dd>
                  </div>
                  <div>
                    <dt>建议目录</dt>
                    <dd>{{ suggestionsPage.selectedSuggestion.suggestedFolder }}</dd>
                  </div>
                  <div>
                    <dt>建议新文件名</dt>
                    <dd>{{ suggestionsPage.selectedSuggestion.suggestedFileName }}</dd>
                  </div>
                  <div>
                    <dt>文件类型</dt>
                    <dd>{{ suggestionsPage.selectedSuggestion.fileType }}</dd>
                  </div>
                </dl>

                <section class="detail-block">
                  <span class="detail-label">标签</span>
                  <div class="suggestion-tags">
                    <a-tag
                      v-for="tag in suggestionsPage.selectedSuggestion.tags"
                      :key="tag"
                      color="blue"
                    >
                      {{ tag }}
                    </a-tag>
                    <span v-if="!suggestionsPage.selectedSuggestion.tags.length" class="muted-text">
                      暂无标签
                    </span>
                  </div>
                </section>

                <section class="detail-block">
                  <span class="detail-label">摘要</span>
                  <p class="summary-box">
                    {{ suggestionsPage.selectedSuggestion.summary || '暂无摘要' }}
                  </p>
                </section>

                <section class="detail-block">
                  <span class="detail-label">关键信息</span>
                  <div class="key-info-grid">
                    <div
                      v-for="item in suggestionsPage.selectedSuggestion.keyInfo"
                      :key="item.label"
                    >
                      <span>{{ item.label }}</span>
                      <strong>{{ item.value }}</strong>
                    </div>
                    <span v-if="!suggestionsPage.selectedSuggestion.keyInfo.length" class="muted-text">
                      暂无结构化字段
                    </span>
                  </div>
                </section>

                <section class="detail-block reason-line">
                  <span class="detail-label">建议原因</span>
                  <p>{{ suggestionsPage.selectedSuggestion.reason }}</p>
                </section>

                <div class="decision-actions">
                  <a-button
                    type="primary"
                    :disabled="!selectedSuggestionIsPending"
                    :loading="isDeciding"
                    @click="decideSuggestion('approve')"
                  >
                    同意
                  </a-button>
                  <a-button :disabled="!selectedSuggestionIsPending">修改</a-button>
                  <a-button
                    danger
                    :disabled="!selectedSuggestionIsPending"
                    @click="decideSuggestion('reject')"
                  >
                    拒绝
                  </a-button>
                  <a-button
                    type="text"
                    :disabled="!selectedSuggestionIsPending"
                    @click="decideSuggestion('later')"
                  >
                    稍后处理
                  </a-button>
                </div>
              </template>
            </a-card>

            <a-card class="file-info-panel">
              <template #title>文件信息</template>
              <a-empty v-if="!suggestionsPage.selectedSuggestion" description="暂无文件信息" />
              <template v-else>
                <div class="file-type-preview">
                  <FilePdfOutlined />
                  <strong>{{ suggestionsPage.selectedSuggestion.fileInfo.type }}</strong>
                </div>
                <dl class="file-info-list">
                  <div>
                    <dt>原始文件名</dt>
                    <dd>{{ suggestionsPage.selectedSuggestion.fileInfo.originalName }}</dd>
                  </div>
                  <div>
                    <dt>文件大小</dt>
                    <dd>{{ suggestionsPage.selectedSuggestion.fileInfo.size }}</dd>
                  </div>
                  <div>
                    <dt>上传时间</dt>
                    <dd>{{ suggestionsPage.selectedSuggestion.fileInfo.uploadedAt }}</dd>
                  </div>
                </dl>
                <span class="detail-label">置信度</span>
                <a-progress
                  :percent="Number.parseInt(suggestionsPage.selectedSuggestion.confidence, 10) || 0"
                  :show-info="false"
                />
                <strong class="confidence-large">
                  {{ suggestionsPage.selectedSuggestion.confidence }}
                </strong>
                <section class="confirm-warning">
                  <strong>{{ selectedSuggestionIsPending ? '需确认后执行' : '已执行完成' }}</strong>
                  <span>
                    {{
                      selectedSuggestionIsPending
                        ? '包含移动目录、重命名和打标签'
                        : '文件已按建议更新到当前路径'
                    }}
                  </span>
                </section>
              </template>
            </a-card>
          </section>

          <section v-else-if="activePage === 'library'" class="page-section library-page">
            <section class="library-summary-grid">
              <a-card class="library-summary-card">
                <span>全部文件</span>
                <strong>{{ libraryPage.summary.totalFiles }}</strong>
              </a-card>
              <a-card class="library-summary-card">
                <span>已整理</span>
                <strong>{{ libraryPage.summary.organizedFiles }}</strong>
              </a-card>
              <a-card class="library-summary-card">
                <span>已索引</span>
                <strong>{{ libraryPage.summary.indexedFiles }}</strong>
              </a-card>
              <a-card class="library-summary-card">
                <span>总大小</span>
                <strong>{{ libraryPage.summary.totalSize }}</strong>
              </a-card>
            </section>

            <a-card class="library-panel">
              <div class="library-toolbar">
                <a-input
                  v-model:value="librarySearch"
                  class="library-search"
                  placeholder="搜索文件名、路径、摘要或标签"
                  allow-clear
                >
                  <template #prefix><SearchOutlined /></template>
                </a-input>
                <a-select v-model:value="libraryStatusFilter" class="library-filter">
                  <a-select-option value="all">全部状态</a-select-option>
                  <a-select-option
                    v-for="status in libraryPage.filters.statuses"
                    :key="status.value"
                    :value="status.value"
                  >
                    {{ status.label }}
                  </a-select-option>
                </a-select>
                <a-select v-model:value="libraryFolderFilter" class="library-filter">
                  <a-select-option value="all">全部目录</a-select-option>
                  <a-select-option
                    v-for="folder in libraryPage.filters.folders"
                    :key="folder"
                    :value="folder"
                  >
                    {{ folder }}
                  </a-select-option>
                </a-select>
              </div>

              <a-empty v-if="!filteredLibraryFiles.length" description="暂无匹配文件" />
              <div v-else class="library-file-list">
                <article v-for="file in filteredLibraryFiles" :key="file.id" class="library-file-row">
                  <div class="library-file-icon">
                    <FilePdfOutlined v-if="file.fileType === 'PDF'" />
                    <FileOutlined v-else />
                    <span>{{ file.fileType }}</span>
                  </div>
                  <div class="library-file-main">
                    <div class="library-file-title">
                      <strong>{{ file.fileName }}</strong>
                      <a-tag :color="libraryStatusColor(file.rawStatus)">{{ file.status }}</a-tag>
                    </div>
                    <span class="library-file-path">{{ file.folder }}</span>
                    <p>{{ file.summary || file.currentPath }}</p>
                    <div class="library-tag-row">
                      <a-tag v-for="tag in file.tags" :key="tag" color="blue">{{ tag }}</a-tag>
                      <span v-if="!file.tags.length" class="muted-text">暂无标签</span>
                    </div>
                  </div>
                  <dl class="library-file-meta">
                    <div>
                      <dt>大小</dt>
                      <dd>{{ file.sizeLabel }}</dd>
                    </div>
                    <div>
                      <dt>根目录</dt>
                      <dd>{{ file.storageRoot }}</dd>
                    </div>
                    <div>
                      <dt>更新时间</dt>
                      <dd>{{ formatLibraryUpdatedAt(file.updatedAt) }}</dd>
                    </div>
                  </dl>
                </article>
              </div>
            </a-card>
          </section>

          <section v-else class="page-section placeholder-page">
            <a-empty description="这个页面稍后实现" />
          </section>
        </a-spin>
      </main>
    </div>
  </a-config-provider>
</template>
