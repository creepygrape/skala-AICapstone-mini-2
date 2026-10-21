<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { searchScenes } from './api/search'
import { applyEvent, abortRunning } from './api/steps'
import { fetchCueContext } from './api/context'
import { loadConversations, saveConversations, followUpPayload, newConversation, newTurn, evidenceKey } from './stores/conversations'
import SidebarHistory from './components/SidebarHistory.vue'
import AgentProgress from './components/AgentProgress.vue'
import ResultList from './components/ResultList.vue'
import DetailPanel from './components/DetailPanel.vue'

const conversations = ref(loadConversations())
const activeId = ref(null)
const query = ref('')
const busy = ref(false)
const now = ref(performance.now())
const selected = ref(null)        // {key, item}
const cues = ref([])
const cuesLoading = ref(false)
const cuesError = ref('')
const timingSampled = ref(false)
const sidebarOpen = ref(false)
const detailOpen = ref(false)
const thread = ref(null)
const examples = ['리쿠가 마니또 뽑다가 자기 자신을 뽑은 장면', '료칸이 뭔지 물어본 부분', '료칸이 뭔지 물어본 멤버가 누구야?']
let controller, ticker, contextController

const active = computed(() => conversations.value.find(c => c.id === activeId.value) || null)
const sorted = computed(() => [...conversations.value].sort((a, b) => b.updatedAt - a.updatedAt))
const toBottom = () => nextTick(() => { if (thread.value) thread.value.scrollTop = thread.value.scrollHeight })

watch(conversations, list => saveConversations(list), { deep: true })

onMounted(async () => {
  try {
    const r = await fetch('/api/videos')
    if (r.ok) {
      const videos = (await r.json()).videos
      timingSampled.value = videos.length > 0 && videos.every(video => video.timing_verified)
    }
  } catch { /* Search displays its own actionable error. */ }
})
onUnmounted(() => { controller?.abort(); contextController?.abort(); clearInterval(ticker) })

// Open the quoted cue with its neighbours; stale responses from earlier clicks are ignored.
// `open` is true only for a user click, so restoring history never covers the chat on small screens.
async function select(item, open = false) {
  const key = evidenceKey(item)
  selected.value = { key, item }
  if (open) detailOpen.value = true
  contextController?.abort()
  contextController = new AbortController()
  const mine = contextController
  cues.value = []; cuesError.value = ''; cuesLoading.value = true
  try {
    const reply = await fetchCueContext(item.video_id, item.cue_ids[0], mine.signal)
    if (mine === contextController) cues.value = reply.cues
  } catch (e) {
    if (e.name !== 'AbortError' && mine === contextController) cuesError.value = e.message
  } finally {
    if (mine === contextController) cuesLoading.value = false
  }
}

function openConversation(id) {
  activeId.value = id
  sidebarOpen.value = false
  selected.value = null; detailOpen.value = false; cues.value = []
  const last = [...(active.value?.turns || [])].reverse().find(t => t.response?.results.length)
  if (last) select(last.response.results[0])
  toBottom()
}
function newChat() {
  activeId.value = null
  sidebarOpen.value = false
  selected.value = null; detailOpen.value = false; cues.value = []
}
function removeConversation(id) {
  conversations.value = conversations.value.filter(c => c.id !== id)
  if (activeId.value === id) newChat()
}

async function submit(text = query.value) {
  const question = text.trim()
  if (!question || busy.value) return
  if (!active.value) {
    conversations.value.unshift(newConversation(question))
    activeId.value = conversations.value[0].id
  }
  const convo = active.value
  const context = followUpPayload(convo)
  convo.turns.push(newTurn(question))
  const turn = convo.turns[convo.turns.length - 1]
  query.value = ''
  controller = new AbortController()
  busy.value = true
  clearInterval(ticker); ticker = setInterval(() => { now.value = performance.now() }, 100)
  const timeout = setTimeout(() => controller.abort(), 70000)
  toBottom()
  try {
    turn.response = await searchScenes(question, controller.signal, (event, data) => {
      turn.steps = applyEvent(turn.steps, event, data, performance.now())
      if (event === 'done') turn.doneMs = data.elapsed_ms
      toBottom()
    }, context)
    turn.status = 'done'
    if (turn.response.results.length) select(turn.response.results[0])
  } catch (e) {
    turn.status = 'error'
    turn.error = e.name === 'AbortError' ? '검색이 취소되었거나 시간이 초과됐습니다. 다시 시도해 주세요.' : e.message
  } finally {
    clearTimeout(timeout); clearInterval(ticker); busy.value = false
    turn.steps = abortRunning(turn.steps, performance.now())
    convo.updatedAt = Date.now()
    toBottom()
  }
}
function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit() }
}
</script>

<template>
  <div class="app" :class="{ 'sidebar-open': sidebarOpen, 'detail-open': detailOpen }">
    <SidebarHistory :conversations="sorted" :active-id="activeId" :busy="busy"
      @new="newChat" @open="openConversation" @remove="removeConversation" />
    <main class="chat">
      <header class="topbar">
        <button type="button" class="menu" aria-label="검색 기록 열기" @click="sidebarOpen = !sidebarOpen">☰</button>
        <strong>{{ active?.title || '새 대화' }}</strong>
        <button v-if="selected" type="button" class="scene-toggle" @click="detailOpen = true">선택한 장면 보기</button>
      </header>
      <div ref="thread" class="thread">
        <section v-if="!active" class="hero">
          <p class="eyebrow">SUBTITLE SCENE FINDER</p>
          <h1>그 장면, 뭐였더라?</h1>
          <p>정확한 대사나 제목을 몰라도 괜찮아요. 기억나는 상황으로 영상 속 장면을 찾아보세요.</p>
          <div class="examples"><button v-for="example in examples" :key="example" type="button" :disabled="busy" @click="submit(example)">{{ example }}</button></div>
        </section>
        <template v-else>
          <div v-for="turn in active.turns" :key="turn.id" class="turn">
            <p class="bubble user">{{ turn.query }}</p>
            <div class="bubble agent" :aria-busy="turn.status === 'running'">
              <AgentProgress :steps="turn.steps" :busy="turn.status === 'running'" :now="now" :done-ms="turn.doneMs" />
              <p v-if="turn.status === 'error'" role="alert" class="notice error">{{ turn.error }}</p>
              <ResultList v-if="turn.response" :response="turn.response" :selected-key="selected?.key" @select="item => select(item, true)" />
            </div>
          </div>
        </template>
      </div>
      <form class="composer" @submit.prevent="submit()">
        <textarea v-model="query" rows="1" maxlength="1000" :disabled="busy" aria-label="찾고 싶은 장면 설명"
          :placeholder="active ? '이어서 질문해 보세요. 예: 다른 장면도 보여줘' : '기억나는 장면을 자연어로 입력해 보세요'" @keydown="onKeydown"></textarea>
        <button v-if="busy" type="button" class="cancel" data-testid="cancel" @click="controller?.abort()">취소</button>
        <button v-else type="submit" :disabled="!query.trim()" aria-label="보내기">보내기</button>
      </form>
      <footer>영상·음성 자체를 분석하지 않고, 확보한 자막과 영상 정보 안에서만 찾습니다.</footer>
    </main>
    <div class="scrim" @click="sidebarOpen = false; detailOpen = false"></div>
    <DetailPanel :item="selected?.item" :cues="cues" :target-cue-id="selected ? String(selected.item.cue_ids[0]) : ''"
      :loading="cuesLoading" :error="cuesError" :timing-sampled="timingSampled" :open="detailOpen" @close="detailOpen = false" />
  </div>
</template>
