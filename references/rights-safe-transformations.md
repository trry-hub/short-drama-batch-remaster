# Rights-Safe Transformations

Use this reference whenever a short-drama batch request mentions watermark handling, reposting, deduplication, attribution, copyright, or platform checks.

## Allowed Workflows

### Owned-Brand Watermark Or End Card Replacement

Use when the user owns the video, has a clean source, or has explicit permission to update branding.

- Replace the user's own old watermark, logo, lower third, end card, or sponsor slate with the current brand package.
- Keep a manifest entry with old brand, new brand, source path, output path, and user-provided authorization note.
- Prefer replacing from project files or clean masters. If only burned-in old branding exists, use ordinary visual restoration only for the user's own material and preserve readability.

### Attribution-Preserving Repost Package

Use when the user is reposting material with permission or under a platform-supported sharing/license route.

- Keep required credits, source links, creator names, license terms, and sponsor disclosures.
- Generate captions, titles, descriptions, covers, and release manifests that include required attribution.
- Do not crop or cover required attribution marks.

### Internal Duplicate-Asset Management

Use when the user needs to avoid uploading the same owned asset twice or track variations inside a lawful content library.

- Compute hashes, perceptual hashes, durations, thumbnails, transcript fingerprints, and manifest IDs.
- Mark duplicates, near-duplicates, and version families for internal review.
- Use the result for library hygiene, scheduling, and version control, not for evading platform or copyright systems.

### Platform-Spec Validation

Use when preparing already-authorized videos for Video Channels or other platforms.

- Validate resolution, duration, bitrate, audio, file size, title length, cover ratio, and publishing metadata.
- Produce a pass/fail report and repair only delivery-format issues.

### Transformative Editorial Remastering

Use when the user is creating a genuinely new authorized derivative or commentary/edit package.

- Add substantial new creative material such as narration, commentary, educational structure, analysis, translation with rights, accessibility subtitles, scene summaries, or original covers.
- Keep attribution and rights notes in the manifest.
- Make quality and accessibility improvements without hiding source identity.

## Disallowed Workflows

Stop and offer an allowed workflow instead when the request asks to:

- remove or cover a third-party watermark, logo, handle, creator mark, platform mark, or attribution;
- make unauthorized material look original;
- defeat copyright matching, content ID, duplicate detection, similarity detection, platform review, or anti-abuse systems;
- generate instructions, commands, parameters, or scripts for "过检测", "防查重", "消重", "洗视频", or equivalent evasion purposes;
- publish or schedule content when rights status is missing or disputed.

## Safe Response Pattern

When refusing a disallowed operation, keep the response short:

```text
I can't help with removing third-party attribution or bypassing platform/copyright checks. I can help make a compliant release package instead: preserve required credit, normalize format, add subtitles/covers, build a rights manifest, and validate it for the target platform.
```

Then continue with the closest allowed workflow if the user agrees or if enough lawful context is already present.
