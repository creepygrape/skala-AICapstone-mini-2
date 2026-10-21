<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { searchScenes, timestamp } from './api/search'

const query = ref('')
const busy = ref(false)
const error = ref('')
const response = ref(null)
const videoCount = ref(null)
const timingSampled = ref(false)
const progress = ref(null)
let controller
const examples = ['리쿠가 마니또 뽑다가 자기 자신을 뽑은 장면', '료칸이 뭔지 물어본 부분', '료칸이 뭔지 물어본 멤버가 누구야?']

onMounted(async () => {
  try {
    const r = await fetch('/api/videos')
    if (r.ok) {
      const videos = (await r.json()).videos
      videoCount.value = videos.length
      timingSampled.value = videos.length > 0 && videos.every(video => video.timing_verified)
    }
  } catch { /* Search displays its own actionable error. */ }
})
onUnmounted(() => controller?.abort())

async function submit() {
  if (!query.value.trim() || busy.value) return
  controller = new AbortController()
  busy.value = true; error.value = ''; response.value = null; progress.value = null
  const timeout = setTimeout(() => controller.abort(), 70000)
  try {
    response.value = await searchScenes(query.value, controller.signal, (event, data) => {
      if (['routing','searching','validating','replanning'].includes(event)) progress.value = { event, ...data }
    })
  }
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
    <p v-if="busy" role="status" class="notice progress">{{ progress?.message || '검색을 준비하고 있어요.' }} <span v-if="progress?.attempt !== undefined && progress.event !== 'routing'">{{ progress.attempt + 1 }}차 검색</span><button @click="controller?.abort()">취소</button></p>
    <p v-if="error" role="alert" class="notice error">{{ error }}</p>
    <section v-if="response" aria-live="polite" class="results">
      <h2>{{ response.results.length ? response.status === 'found' ? '기억과 일치하는 장면' : '확정하기 어려운 검색 후보' : response.status === 'unsupported' ? response.warnings.includes('evidence_rejected') ? '원문 근거를 확인하지 못했어요' : response.warnings.includes('subtitle_only_scope') ? '자막으로 확인할 수 없는 요청이에요' : '확인할 근거가 부족해요' : '관련 자막을 찾지 못했어요' }}</h2>
      <p v-if="!response.results.length">다른 표현이나 기억나는 단어로 다시 검색해 보세요. 영상에 장면이 없다는 뜻은 아닙니다.</p>
      <p v-else-if="response.status === 'partial'" class="notice">원문과 시각은 확인했지만 의미 검증을 완료하지 못했습니다.</p>
      <p v-else-if="response.status === 'ambiguous'" class="notice">관련 가능성이 있지만 질문과 장면의 일치를 확정하기 어렵습니다.</p>
      <p v-if="response.warnings.includes('speaker_unknown')" class="notice">자막에는 화자 정보가 없어 발화자는 확인할 수 없습니다.</p>
      <p v-if="response.warnings.includes('evidence_rejected')" class="notice">원문 근거를 확인하지 못한 후보는 제외했습니다.</p>
      <article v-for="item in response.results" :key="`${item.video_id}:${item.cue_ids.join(',')}`">
        <div class="card-top"><span class="tag">{{ item.evidence_type === 'mixed' ? '대사·편집 설명 혼합' : item.evidence_type === 'editorial' ? '편집 설명' : '원문 자막' }}</span><span>{{ timestamp(item.start_seconds) }} – {{ timestamp(item.end_seconds) }}</span></div>
        <h3>{{ item.title }}</h3>
        <blockquote>{{ item.evidence_text }}</blockquote>
        <p>{{ item.explanation_ko }}</p>
        <div class="card-bottom"><span>화자 미확인 · 번역 자막 기준</span><a :href="item.url" target="_blank" rel="noopener noreferrer">해당 장면 보기 ↗<span class="sr-only"> (YouTube 새 창)</span></a></div>
      </article>
    </section>
    <footer>영상·음성 자체를 분석하지 않습니다. {{ timingSampled ? '영상별 일부 시점의 내용 일치를 사용자 표본 확인했습니다. 전체 자막 시각의 정확도를 보장하지는 않습니다.' : '원본 영상과 자막 시각의 일치 여부는 추가 확인 중입니다.' }}</footer>
  </main>
</template>
