<template>
  <div class="flex min-h-screen pattern-polka relative overflow-hidden">
    <!-- Floating Memphis Decos -->
    <MemphisDeco type="squiggle" color="text-[#9B59B6]" size="w-24 h-24" customClass="absolute top-[10%] right-[15%] rotate-[-15deg] animate-[wobble_6s_ease-in-out_infinite]" />
    <MemphisDeco type="cross" color="text-[#FF8A80]" size="w-12 h-12" customClass="absolute bottom-[20%] right-[30%] rotate-45 animate-[spin_10s_linear_infinite]" />
    <MemphisDeco type="ring" color="text-[#2DD4A8]" size="w-32 h-32" customClass="absolute top-[40%] left-[280px] opacity-40 animate-[pulse_5s_ease-in-out_infinite]" />
    <MemphisDeco type="triangle" color="text-[#FFE066]" size="w-16 h-16" customClass="absolute bottom-[15%] left-[350px] rotate-[30deg]" />
    <MemphisDeco type="dots" color="text-[#2D2D2D]" size="w-20 h-20" customClass="absolute top-[5%] left-[50%] opacity-20" />

    <AppSidebar />
    <main class="ml-[240px] flex-1 flex flex-col min-h-screen bg-[#F5F0E8] bg-opacity-80 backdrop-blur-sm relative z-10 border-l-[3px] border-[#2D2D2D]">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import AppSidebar from './components/AppSidebar.vue'
import MemphisDeco from './components/MemphisDeco.vue'
</script>
