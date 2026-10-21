import { isVideoId } from './youtube'

// YouTube's public thumbnail host; no API key and no backend metadata needed.
export const thumbnailUrl = videoId => isVideoId(videoId) ? `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg` : ''

// Same watch URL, different start second (result URLs end with &t=Ns).
export function urlAt(url, seconds) {
  return `${url.replace(/([&?])t=\d+s?$/, '').replace(/[&?]$/, '')}${url.includes('?') ? '&' : '?'}t=${Math.floor(seconds)}s`
}
