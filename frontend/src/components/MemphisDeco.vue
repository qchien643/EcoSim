<template>
  <svg 
    v-if="type === 'squiggle'"
    :class="className" 
    viewBox="0 0 100 100" 
    xmlns="http://www.w3.org/2000/svg"
  >
    <path d="M10 50 Q 25 10, 50 50 T 90 50" fill="none" stroke="currentColor" stroke-width="12" stroke-linecap="round"/>
  </svg>
  
  <svg 
    v-else-if="type === 'cross'"
    :class="className"
    viewBox="0 0 100 100" 
    xmlns="http://www.w3.org/2000/svg"
  >
    <path d="M50 10 L50 90 M10 50 L90 50" stroke="currentColor" stroke-width="16" stroke-linecap="square"/>
  </svg>
  
  <svg 
    v-else-if="type === 'dots'"
    :class="className"
    viewBox="0 0 100 100" 
    xmlns="http://www.w3.org/2000/svg"
  >
    <circle cx="20" cy="20" r="8" fill="currentColor"/>
    <circle cx="50" cy="20" r="8" fill="currentColor"/>
    <circle cx="80" cy="20" r="8" fill="currentColor"/>
    <circle cx="20" cy="50" r="8" fill="currentColor"/>
    <circle cx="50" cy="50" r="8" fill="currentColor"/>
    <circle cx="80" cy="50" r="8" fill="currentColor"/>
    <circle cx="20" cy="80" r="8" fill="currentColor"/>
    <circle cx="50" cy="80" r="8" fill="currentColor"/>
    <circle cx="80" cy="80" r="8" fill="currentColor"/>
  </svg>
  
  <svg 
    v-else-if="type === 'ring'"
    :class="className"
    viewBox="0 0 100 100" 
    xmlns="http://www.w3.org/2000/svg"
  >
    <circle cx="50" cy="50" r="35" fill="none" stroke="currentColor" stroke-width="14"/>
  </svg>

  <svg 
    v-else-if="type === 'triangle'"
    :class="className"
    viewBox="0 0 100 100" 
    xmlns="http://www.w3.org/2000/svg"
  >
    <polygon points="50,15 90,85 10,85" fill="none" stroke="currentColor" stroke-width="12" stroke-linejoin="miter"/>
  </svg>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  type: {
    type: String,
    required: true,
    validator: (v) => ['squiggle', 'cross', 'dots', 'ring', 'triangle'].includes(v)
  },
  color: {
    type: String,
    default: 'text-gray-800'
  },
  size: {
    type: String,
    default: 'w-12 h-12'
  },
  animation: {
    type: String,
    default: '' // e.g. 'animate-spin-slow', 'animate-bounce'
  },
  customClass: {
    type: String,
    default: ''
  }
});

const className = computed(() => {
  return `${props.color} ${props.size} ${props.animation} ${props.customClass} opacity-80`;
});
</script>

<style scoped>
/* Optional custom keyframes for subtle memphis floating can be added here / global css */
</style>
