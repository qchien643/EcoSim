<template>
  <div class="flex min-h-screen relative overflow-hidden memphis-app-root">
    <!-- Bold Floating Memphis Decorators — green-themed -->
    <MemphisDeco type="squiggle" color="text-[#66BB6A]" size="w-32 h-32" customClass="fixed top-[8%] right-[10%] rotate-[-15deg] opacity-60 z-[1] animate-[wobble_6s_ease-in-out_infinite]" />
    <MemphisDeco type="cross" color="text-[#FFE500]" size="w-20 h-20" customClass="fixed bottom-[25%] right-[25%] rotate-45 opacity-50 z-[1] animate-[spin_12s_linear_infinite]" />
    <MemphisDeco type="ring" color="text-[#4CAF50]" size="w-44 h-44" customClass="fixed top-[35%] right-[5%] opacity-25 z-[1] animate-[pulse_5s_ease-in-out_infinite]" />
    <MemphisDeco type="triangle" color="text-[#FF2D78]" size="w-24 h-24" customClass="fixed bottom-[10%] left-[280px] rotate-[30deg] opacity-40 z-[1]" />
    <MemphisDeco type="dots" color="text-[#66BB6A]" size="w-28 h-28" customClass="fixed top-[3%] left-[55%] opacity-12 z-[1]" />
    <MemphisDeco type="cross" color="text-[#000]" size="w-14 h-14" customClass="fixed bottom-[5%] right-[15%] rotate-12 opacity-30 z-[1]" />

    <AppSidebar />
    <main class="main-content ml-[240px] flex-1 flex flex-col min-h-screen relative z-10 border-l-[4px] border-[#000]">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import AppSidebar from './components/AppSidebar.vue'
import MemphisDeco from './components/MemphisDeco.vue'
</script>

<style>
/* Memphis App Root — bold patterned background */
.memphis-app-root {
  background-color: #FFF5E4;
  background-image:
    /* Colorful confetti scatter — green-dominant Memphis */
    url("data:image/svg+xml,%3Csvg width='80' height='80' xmlns='http://www.w3.org/2000/svg'%3E%3Crect x='8' y='8' width='6' height='6' fill='%2366BB6A' fill-opacity='0.25' transform='rotate(45 11 11)'/%3E%3Ccircle cx='45' cy='20' r='4' fill='%23FFE500' fill-opacity='0.2'/%3E%3Cpolygon points='65,55 72,70 58,70' fill='%234CAF50' fill-opacity='0.2'/%3E%3Crect x='18' y='55' width='8' height='3' fill='%23000' fill-opacity='0.08' transform='rotate(-25 22 56)'/%3E%3Ccircle cx='70' cy='12' r='3' fill='%23FF2D78' fill-opacity='0.2'/%3E%3Crect x='48' y='62' width='5' height='5' fill='%2366BB6A' fill-opacity='0.15'/%3E%3C/svg%3E");
  background-size: 80px 80px;
}

/* Main content — Memphis patterned surface, NOT plain beige */
.main-content {
  background-color: rgba(255, 245, 228, 0.88);
  background-image:
    /* Grid of small green dots — Memphis halftone motif */
    url("data:image/svg+xml,%3Csvg width='24' height='24' xmlns='http://www.w3.org/2000/svg'%3E%3Ccircle cx='12' cy='12' r='1.5' fill='%2366BB6A' fill-opacity='0.1'/%3E%3C/svg%3E");
  background-size: 24px 24px;
}



/* Big yellow diamond — bottom-right */
.main-content::after {
  content: '';
  position: fixed;
  bottom: 30px;
  right: 80px;
  width: 120px;
  height: 120px;
  background: #66BB6A;
  border: 4px solid #000;
  transform: rotate(45deg);
  opacity: 0.15;
  pointer-events: none;
  z-index: 0;
}
</style>
