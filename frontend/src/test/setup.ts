import { config, enableAutoUnmount } from '@vue/test-utils'
import { afterEach } from 'vitest'

config.global.stubs = {
  teleport: true,
  transition: true,
}

enableAutoUnmount(afterEach)
