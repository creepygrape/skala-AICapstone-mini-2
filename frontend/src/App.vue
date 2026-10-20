<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { searchScenes, timestamp } from './api/search'

const query = ref('')
const busy = ref(false)
const error = ref('')
const response = ref(null)
const videoCount = ref(null)
let controller
const examples = ['리쿠가 마니또 뽑다가 자기 자신을 뽑은 장면', '료칸이 뭔지 물어본 부분', '료칸이 뭔지 물어본 멤버가 누구야?']

onMounted(async () => {
  try {
    const r = await fetch('/api/videos')
    if (r.ok) videoCount.value = (await r.json()).videos.length
  } catch { /* Search displays its own actionable error. */ }
})
onUnmounted(() => controller?.abort())

async function submit() {
  if (!query.value.trim() || busy.value) return
  controller = new AbortController()
  busy.value = true; error.value = ''; response.value = null
  const timeout = setTimeout(() => controller.abort(), 70000)
  try { response.value = await searchScenes(query.value, controller.signal) }
  catch (e) { error.value = e.name === 'AbortError' ? '검색이 취소되었거나 시간이 초과됐습니다. 다시 시도해 주세요.' : e.message }
  finally { clearTimeout(timeout); busy.value = false }
}
</script>

<template>
  <main>
    <header><a class="brand" href="/">WISH FINDER<span>기억 속 장면 찾기</span></a><span class="tag">{{ videoCount === null ? '로컬 자막 검색' : `등록 영상 ${videoCount}편` }}</span></header>
    <section class="intro">
      <p class="eyebrow">NCT WISH SCENE FINDER</p>
      <h1>그 장면, 뭐였더라?</h1>
      <p>정확한 대사나 제목을 몰라도 괜찮아요.<br />기억나는 상황으로 영상 속 장면을 찾아보세요.</p>
    </section>
    <form @submit.prevent="submit">
      <label for="query">어떤 장면이 기억나나요?</label>
      <textarea id="query" v-model="query" maxlength="1000" :disabled="busy" placeholder="예: 리쿠가 마니또를 뽑다가 자기 자신을 뽑은 장면" rows="3" required></textarea>
      <div class="form-bottom"><span>확보한 자막과 영상 정보 안에서 검색합니다.</span><button type="submit" :disabled="busy || !query.trim()">{{ busy ? '찾는 중…' : '장면 찾기 ↗' }}</button></div>
    </form>
    <div class="examples"><span>이렇게 찾아보세요</span><button v-for="example in examples" :key="example" :disabled="busy" @click="query = example">{{ example }}</button></div>
    <p v-if="busy" role="status" class="notice">관련 자막을 검색하고 원문과 시점을 확인하고 있어요. <button @click="controller?.abort()">취소</button></p>
    <p v-if="error" role="alert" class="notice error">{{ error }}</p>
    <section v-if="response" aria-live="polite" class="results">
      <h2>{{ response.results.length ? '기억과 가까운 검색 후보' : '관련 자막을 찾지 못했어요' }}</h2>
      <p v-if="!response.results.length">다른 표현이나 기억나는 단어로 다시 검색해 보세요. 영상에 장면이 없다는 뜻은 아닙니다.</p>
      <p v-else class="notice">현재는 기본 검색 단계입니다. 원문과 시각은 확인했지만 질문과의 의미 일치는 아직 검증하지 않았어요. 자막만으로 발화자는 확인할 수 없습니다.</p>
      <article v-for="item in response.results" :key="`${item.video_id}:${item.cue_ids.join(',')}`">
        <div class="card-top"><span class="tag">{{ item.evidence_type === 'mixed' ? '대사·편집 설명 혼합' : item.evidence_type === 'editorial' ? '편집 설명' : '원문 자막' }}</span><span>{{ timestamp(item.start_seconds) }} – {{ timestamp(item.end_seconds) }}</span></div>
        <h3>{{ item.title }}</h3>
        <blockquote>{{ item.evidence_text }}</blockquote>
        <p>{{ item.explanation_ko }}</p>
        <div class="card-bottom"><span>화자 미확인 · 번역 자막 기준</span><a :href="item.url" target="_blank" rel="noopener noreferrer">해당 장면 보기 ↗<span class="sr-only"> (YouTube 새 창)</span></a></div>
      </article>
    </section>
    <footer>영상·음성 자체를 분석하지 않습니다. 원본 영상과 자막 시각의 일치 여부는 추가 확인 중입니다.</footer>
  </main>
</template>
