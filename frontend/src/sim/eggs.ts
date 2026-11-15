// Easter eggs. Nothing here touches the plan or the physics of the walk.
//  1. Off the route, Perseverance (about 3,800 km from home in Jezero crater) has its mast camera trained on a
//     cardboard picture of Mars that an alien is holding up for it.
//  2. By the crew rover lies a skateboard. E picks it up, B rides it (physics in skate.ts).
import * as THREE from 'three';

const std = (color: number, roughness = 0.7, metalness = 0) => new THREE.MeshStandardMaterial({ color, roughness, metalness });

/** Perseverance, simplified: about 3 m long, 2.7 m wide, 2.2 m to the top of the mast; six 52.5 cm wheels. */
export function makePerseverance(): { group: THREE.Group; head: THREE.Group } {
  const g = new THREE.Group();
  const white = std(0xe7e3da, 0.55);
  const grey = std(0x8d8f93, 0.5, 0.35);
  const dark = std(0x2a2b2e, 0.8);
  const gold = std(0xc9a14a, 0.35, 0.7);
  const alu = std(0xb9bcc0, 0.35, 0.8);

  const body = new THREE.Mesh(new THREE.BoxGeometry(1.95, 0.62, 2.45), white); // the warm electronics box
  body.position.y = 1.0;
  g.add(body);
  const deck = new THREE.Mesh(new THREE.BoxGeometry(2.0, 0.05, 2.5), grey);
  deck.position.y = 1.33;
  g.add(deck);
  // RTG at the back, tilted, with its cooling fins
  const rtg = new THREE.Group();
  const core = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.2, 0.75, 16), dark);
  rtg.add(core);
  for (let i = 0; i < 8; i++) {
    const fin = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.7, 0.32), dark);
    fin.rotation.y = (i / 8) * Math.PI;
    rtg.add(fin);
  }
  rtg.position.set(0, 1.35, 1.45);
  rtg.rotation.x = 0.75;
  g.add(rtg);
  // six wheels on a rocker-bogie
  for (const side of [-1, 1]) {
    for (const z of [-1.0, 0.05, 1.05]) {
      const w = new THREE.Mesh(new THREE.CylinderGeometry(0.2625, 0.2625, 0.4, 20), alu);
      w.rotation.z = Math.PI / 2;
      w.position.set(side * 1.25, 0.2625, z);
      g.add(w);
      const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.42, 10), dark);
      hub.rotation.z = Math.PI / 2;
      hub.position.copy(w.position);
      g.add(hub);
    }
    const rocker = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.07, 2.2), grey);
    rocker.position.set(side * 1.12, 0.62, 0.0);
    rocker.rotation.x = 0.08;
    g.add(rocker);
    for (const [z, h] of [[-1.0, 0.25], [0.05, 0.3], [1.05, 0.25]] as const) {
      const leg = new THREE.Mesh(new THREE.BoxGeometry(0.06, h + 0.15, 0.06), grey);
      leg.position.set(side * 1.12, 0.45, z);
      g.add(leg);
    }
  }
  // high-gain antenna (hexagon) and the mast at the front right
  const hga = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.3, 0.05, 6), white);
  hga.position.set(-0.55, 1.5, 0.6);
  hga.rotation.x = -0.5;
  g.add(hga);
  const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.95, 12), white);
  mast.position.set(0.7, 1.83, -0.95);
  g.add(mast);
  const head = new THREE.Group(); // remote sensing mast head: SuperCam and the Mastcam-Z pair
  head.position.set(0.7, 2.35, -0.95);
  const box = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.26, 0.3), white);
  head.add(box);
  const supercam = new THREE.Mesh(new THREE.CylinderGeometry(0.085, 0.085, 0.06, 20), dark);
  supercam.rotation.x = Math.PI / 2;
  supercam.position.set(0, 0.02, -0.16);
  head.add(supercam);
  for (const x of [-0.17, 0.17]) {
    const eye = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.08, 14), gold);
    eye.rotation.x = Math.PI / 2;
    eye.position.set(x, -0.04, -0.17);
    head.add(eye);
  }
  g.add(head);
  // the robotic arm, folded at the front, with its turret
  const arm = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.08, 0.08), grey);
  arm.position.set(0, 0.95, -1.35);
  g.add(arm);
  const turret = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.3, 0.3), alu);
  turret.position.set(0.75, 0.95, -1.45);
  g.add(turret);
  g.traverse((o) => {
    if (o instanceof THREE.Mesh) o.castShadow = true;
  });
  return { group: g, head };
}

/** The picture on the cardboard: a postcard of Mars, drawn by hand (by someone who has been to Mars). */
function marsPicture(): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = 512;
  c.height = 352;
  const x = c.getContext('2d') as CanvasRenderingContext2D;
  // cardboard
  x.fillStyle = '#b8895a';
  x.fillRect(0, 0, 512, 352);
  for (let i = 0; i < 40; i++) {
    x.fillStyle = `rgba(90, 60, 30, ${0.04 + 0.04 * Math.sin(i)})`;
    x.fillRect(0, i * 9, 512, 2);
  }
  // the photo: sky, a sun, a mesa, dunes
  const px = 34;
  const py = 30;
  const pw = 444;
  const ph = 262;
  const sky = x.createLinearGradient(0, py, 0, py + ph * 0.6);
  sky.addColorStop(0, '#b77d52');
  sky.addColorStop(1, '#e6c39a');
  x.fillStyle = sky;
  x.fillRect(px, py, pw, ph);
  x.fillStyle = '#fff4e2';
  x.beginPath();
  x.arc(px + pw * 0.78, py + ph * 0.22, 11, 0, Math.PI * 2);
  x.fill();
  x.fillStyle = '#8a5a3a';
  x.beginPath();
  x.moveTo(px, py + ph * 0.62);
  x.lineTo(px + pw * 0.18, py + ph * 0.5);
  x.lineTo(px + pw * 0.42, py + ph * 0.47);
  x.lineTo(px + pw * 0.55, py + ph * 0.56);
  x.lineTo(px + pw, py + ph * 0.6);
  x.lineTo(px + pw, py + ph);
  x.lineTo(px, py + ph);
  x.fill();
  for (let k = 0; k < 5; k++) {
    x.fillStyle = ['#c1814f', '#b57345', '#cf9461', '#a8683d', '#d9a06c'][k];
    x.beginPath();
    x.moveTo(px, py + ph * (0.68 + k * 0.07));
    for (let s = 0; s <= 8; s++) x.quadraticCurveTo(px + (pw / 8) * (s - 0.5), py + ph * (0.63 + k * 0.07), px + (pw / 8) * s, py + ph * (0.68 + k * 0.07));
    x.lineTo(px + pw, py + ph);
    x.lineTo(px, py + ph);
    x.fill();
  }
  x.strokeStyle = '#f5efe2';
  x.lineWidth = 6;
  x.strokeRect(px, py, pw, ph);
  // tape and a marker caption
  x.fillStyle = 'rgba(235, 228, 200, 0.85)';
  for (const [tx, ty, r] of [[px - 14, py - 6, -0.5], [px + pw - 40, py - 8, 0.5]] as const) {
    x.save();
    x.translate(tx + 27, ty + 9);
    x.rotate(r);
    x.fillRect(-27, -9, 54, 18);
    x.restore();
  }
  x.fillStyle = '#2b1d14';
  x.font = 'bold 30px "Comic Sans MS", "Marker Felt", cursive';
  x.fillText('MARS (real)', px + 8, py + ph + 40);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/**
 * An alien of no known franchise: tall, teal, three eyes, two antennae with glowing tips, holding a cardboard sign
 * up in front of the rover's camera. The sign faces -z of the group; the alien stands behind it.
 */
export function makeAlien(): { group: THREE.Group; head: THREE.Group; armL: THREE.Group; armR: THREE.Group; sign: THREE.Mesh } {
  const g = new THREE.Group();
  const skin = std(0x5cc9b4, 0.45, 0.05);
  const eyeM = std(0x0b0b10, 0.05, 0.6);
  const glow = new THREE.MeshStandardMaterial({ color: 0xffc04a, emissive: 0xffa020, emissiveIntensity: 1.6 });
  const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.16, 0.7, 6, 12), skin);
  torso.position.y = 0.95;
  g.add(torso);
  for (const x of [-0.09, 0.09]) {
    const leg = new THREE.Mesh(new THREE.CapsuleGeometry(0.06, 0.55, 4, 8), skin);
    leg.position.set(x, 0.33, 0);
    g.add(leg);
  }
  const head = new THREE.Group();
  head.position.y = 1.62;
  const skull = new THREE.Mesh(new THREE.SphereGeometry(0.28, 24, 18), skin);
  skull.scale.set(1, 1.15, 0.95);
  head.add(skull);
  for (const [x, y, s] of [[-0.12, 0.04, 1], [0.12, 0.04, 1], [0, 0.17, 0.75]] as const) {
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.07 * s, 16, 12), eyeM);
    eye.scale.set(1.25, 0.8, 0.5);
    eye.position.set(x, y, -0.25);
    head.add(eye);
  }
  for (const x of [-0.12, 0.12]) {
    const stalk = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.35, 6), skin);
    stalk.position.set(x, 0.42, 0);
    stalk.rotation.z = -x * 2;
    head.add(stalk);
    const tip = new THREE.Mesh(new THREE.SphereGeometry(0.045, 12, 10), glow);
    tip.position.set(x * 1.6, 0.6, 0);
    head.add(tip);
  }
  g.add(head);
  // arms up, holding the sign by its top corners
  const arm = (x: number) => {
    const pivot = new THREE.Group();
    pivot.position.set(x, 1.28, 0);
    const a = new THREE.Mesh(new THREE.CapsuleGeometry(0.04, 0.55, 4, 8), skin);
    a.position.y = 0.3;
    pivot.add(a);
    pivot.rotation.x = -0.55;
    pivot.rotation.z = -x * 1.2;
    g.add(pivot);
    return pivot;
  };
  const armL = arm(-0.2);
  const armR = arm(0.2);
  const signMats = [std(0x9c7044, 0.95), std(0x9c7044, 0.95), std(0x9c7044, 0.95), std(0x9c7044, 0.95), std(0xa77a4c, 0.95), new THREE.MeshStandardMaterial({ map: marsPicture(), roughness: 0.9 })];
  const sign = new THREE.Mesh(new THREE.BoxGeometry(1.5, 1.03, 0.025), signMats); // face 5 = -z: the picture
  sign.position.set(0, 1.42, -0.42);
  sign.rotation.x = -0.05;
  g.add(sign);
  g.traverse((o) => {
    if (o instanceof THREE.Mesh) o.castShadow = true;
  });
  return { group: g, head, armL, armR, sign };
}

/** A skateboard: maple deck with grip tape, two trucks, four wheels. Length 0.8 m. */
export function makeSkateboard(): THREE.Group {
  const g = new THREE.Group();
  const deck = new THREE.Mesh(new THREE.BoxGeometry(0.21, 0.02, 0.8), std(0x1c1c1e, 0.95));
  deck.position.y = 0.09;
  g.add(deck);
  const under = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.012, 0.78), std(0x2f7fd8, 0.6));
  under.position.y = 0.074;
  g.add(under);
  for (const z of [-0.27, 0.27]) {
    const truck = new THREE.Mesh(new THREE.BoxGeometry(0.17, 0.035, 0.05), std(0xb9bcc0, 0.3, 0.8));
    truck.position.set(0, 0.055, z);
    g.add(truck);
    for (const x of [-0.09, 0.09]) {
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.027, 0.027, 0.032, 14), std(0xf0e4c8, 0.4));
      wheel.rotation.z = Math.PI / 2;
      wheel.position.set(x, 0.027, z);
      g.add(wheel);
    }
  }
  g.traverse((o) => {
    if (o instanceof THREE.Mesh) o.castShadow = true;
  });
  return g;
}
