// Sound on Mars, synthesized (no recordings): what a suited walker would hear, and how the thin CO2 air changes it.
// Measurements from Perseverance's microphones (Maurice et al. 2022, Nature 605: 653): sound travels at 240 m/s below
// 240 Hz (about 250 m/s above), and high pitches are absorbed fast: 0.21, 0.34 and 0.43 per metre at 3-6, 6-11 and
// 11-15 kHz. Below 2 kHz nothing was measured; the absorption is extrapolated linearly toward zero there.
// - Your footsteps reach you through the suit itself, not the air: loud and unchanged.
// - The rover's idling (a low hum) reaches you through the air: quieter with distance (spherical spreading), duller
//   (a low-pass at the frequency the air has absorbed 20 dB of) and late (distance / 240 m/s).
// - The radio: static when the line of sight to the rover is lost, a chirp when it comes back.

const SPEED_LOW_MPS = 240;
const ABSORB: [number, number][] = [[0, 0], [4500, 0.21], [8500, 0.34], [13000, 0.43]]; // Hz, amplitude per metre

/** The highest frequency that keeps at least -20 dB after `d` metres of Martian air (the low-pass cutoff). */
export function cutoffHz(d: number): number {
  const alpha = Math.log(10) / Math.max(d, 0.1); // amplitude e^(-alpha d) = 0.1
  for (let i = 1; i < ABSORB.length; i++) {
    const [f0, a0] = ABSORB[i - 1];
    const [f1, a1] = ABSORB[i];
    if (alpha <= a1) return f0 + ((alpha - a0) / (a1 - a0)) * (f1 - f0);
  }
  return 20000; // closer than the measurements reach: nothing audible is lost
}

export class SimAudio {
  private ctx: AudioContext;
  private master: GainNode;
  private rover: { gain: GainNode; filter: BiquadFilterNode; delay: DelayNode };
  private noise: AudioBuffer;
  private shadow = false;

  constructor() {
    this.ctx = new AudioContext();
    this.master = this.ctx.createGain();
    this.master.gain.value = 0.6;
    this.master.connect(this.ctx.destination);
    // one second of white noise, reused for footsteps and static
    this.noise = this.ctx.createBuffer(1, this.ctx.sampleRate, this.ctx.sampleRate);
    const ch = this.noise.getChannelData(0);
    for (let i = 0; i < ch.length; i++) ch[i] = Math.random() * 2 - 1;
    // the rover: a diesel-like idle at 45 Hz and its harmonics, travelling through the air to you
    const osc = this.ctx.createOscillator();
    osc.type = 'sawtooth';
    osc.frequency.value = 45;
    const filter = this.ctx.createBiquadFilter();
    filter.type = 'lowpass';
    const delay = this.ctx.createDelay(10);
    const gain = this.ctx.createGain();
    gain.gain.value = 0;
    osc.connect(filter).connect(delay).connect(gain).connect(this.master);
    osc.start();
    this.rover = { gain, filter, delay };
  }

  resume(): void {
    void this.ctx.resume();
  }

  /** The rover is `d` metres away: louder close by, muffled and late far off. */
  roverAt(d: number): void {
    const t = this.ctx.currentTime;
    const loud = Math.min(1, 6 / Math.max(d, 1)) * 0.25; // 1/d spreading, full level within 6 m
    this.rover.gain.gain.setTargetAtTime(loud, t, 0.2);
    this.rover.filter.frequency.setTargetAtTime(Math.min(cutoffHz(d), 12000), t, 0.2);
    this.rover.delay.delayTime.setTargetAtTime(Math.min(d / SPEED_LOW_MPS, 9.9), t, 0.2);
  }

  /** One footstep, heard through the suit: a short thud. */
  footstep(): void {
    const t = this.ctx.currentTime;
    const src = this.ctx.createBufferSource();
    src.buffer = this.noise;
    const f = this.ctx.createBiquadFilter();
    f.type = 'lowpass';
    f.frequency.value = 500 + Math.random() * 200;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.5, t + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.12);
    src.connect(f).connect(g).connect(this.master);
    src.start(t, Math.random() * 0.8, 0.15);
  }

  /** The radio: static when contact is lost, a rising chirp when it is back. */
  radio(inShadow: boolean): void {
    if (inShadow === this.shadow) return;
    this.shadow = inShadow;
    const t = this.ctx.currentTime;
    const g = this.ctx.createGain();
    g.connect(this.master);
    if (inShadow) {
      const src = this.ctx.createBufferSource();
      src.buffer = this.noise;
      const f = this.ctx.createBiquadFilter();
      f.type = 'bandpass';
      f.frequency.value = 2500;
      g.gain.setValueAtTime(0.25, t);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.6);
      src.connect(f).connect(g);
      src.start(t, 0, 0.6);
    } else {
      const osc = this.ctx.createOscillator();
      osc.frequency.setValueAtTime(900, t);
      osc.frequency.exponentialRampToValueAtTime(1800, t + 0.15);
      g.gain.setValueAtTime(0.15, t);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
      osc.connect(g);
      osc.start(t);
      osc.stop(t + 0.22);
    }
  }

  dispose(): void {
    void this.ctx.close();
  }
}
