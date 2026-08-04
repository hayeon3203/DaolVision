import { test, expect } from './coverage-fixtures.js'

test('시나리오만 모드는 이전 모드 입력을 제외하고 no-ref 요청을 보낸다', async ({ page }) => {
  let resolveRequest
  const submitted = new Promise((resolve) => { resolveRequest = resolve })

  await page.route('http://127.0.0.1:8700/jobs', async (route) => {
    resolveRequest(route.request().postDataJSON())
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ job_id: 'no-ref-test-job' }),
    })
  })
  await page.route('http://127.0.0.1:8700/jobs/no-ref-test-job/status', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ status: 'running', phase: 'planning' }),
    }))

  await page.goto('/app/gw-agent')

  // 다른 두 모드에 값을 남겨 둔 뒤 no-ref로 전환한다. 화면에서 숨겨져도
  // React state에는 남아 있으므로 요청 조립이 잘못되면 함께 전송된다.
  await page.getByPlaceholder('한 우주비행사가 노을 지는 발사대에서 로켓을 타고 이륙한다...').fill('참조 없이 만들 여성 모델의 하루')
  await page.locator('input[type="file"]').setInputFiles({
    name: 'stale-reference.png',
    mimeType: 'image/png',
    buffer: Buffer.from('stale image'),
  })
  await page.getByRole('button', { name: '이미지 설명으로 생성' }).click()
  await page.getByPlaceholder('우주복을 입은 우주비행사가 노을 지는 발사대 앞에 서있는 모습, 시네마틱...').fill('이전 모드에서 남은 이미지 설명')
  await page.getByRole('button', { name: '시나리오만' }).click()
  await page.locator('button[type="submit"]').click()

  await expect(submitted).resolves.toEqual({
    script_text: '참조 없이 만들 여성 모델의 하루',
    ref_images: [],
    image_request: '',
  })
})
