<template>
  <div class="flex-1 flex flex-col overflow-hidden">
    <!-- HEADER (TopAppBar) -->
    <header class="h-16 border-b border-[#E0DDD5] bg-[#F5F0E8] flex items-center justify-between px-8 flex-shrink-0">
      <!-- Stepper -->
      <div class="flex items-center gap-4">
        <div v-for="(step, i) in stepLabels" :key="i" class="flex items-center gap-1.5">
          <template v-if="i > 0"><div class="w-4 h-[1px] bg-[#E0DDD5]"></div></template>
          <span v-if="prepareStep > i + 1" class="material-symbols-outlined text-[#66BB6A] text-sm">check_circle</span>
          <div v-else-if="prepareStep === i + 1"
            class="px-2 py-1 bg-[#66BB6A]/10 border border-[#66BB6A]/20 rounded flex items-center gap-1.5">
            <span class="text-[10px] font-mono text-[#66BB6A] font-bold">{{ step.id }}</span>
            <span class="text-[10px] font-sans font-bold text-[#66BB6A] uppercase tracking-wider">{{ step.label }}</span>
          </div>
          <div v-else class="flex items-center gap-1.5">
            <div class="w-4 h-4 rounded-full border border-[#E0DDD5] flex items-center justify-center text-[8px] font-mono text-[#6B6B6B]">{{ step.id }}</div>
            <span class="text-[10px] font-mono text-[#6B6B6B] uppercase tracking-wider">{{ step.label }}</span>
          </div>
        </div>
      </div>
      <div class="flex items-center gap-4">
        <button class="text-[#6B6B6B] hover:text-[#66BB6A] transition-colors">
          <span class="material-symbols-outlined">notifications</span>
        </button>
      </div>
    </header>

    <!-- SUB-NAVIGATION TABS -->
    <div class="px-8 border-b border-[#E0DDD5] flex items-center gap-8 h-12 bg-[#FFFFFF] flex-shrink-0">
      <button v-for="tab in tabs" :key="tab" class="h-full px-1 text-xs font-sans font-medium transition-colors"
        :class="activeTab === tab ? 'font-semibold text-[#66BB6A] border-b-2 border-[#66BB6A] tracking-wide' : 'text-[#6B6B6B] hover:text-[#2D2D2D]'"
        @click="activeTab = tab">{{ tab }}</button>
    </div>

    <!-- Error -->
    <div v-if="error" class="mx-8 mt-4 bg-[#FBF8F3] border-l-2 border-[#FF8A80] px-6 py-3 flex items-center gap-3 flex-shrink-0">
      <span class="material-symbols-outlined text-[#FF8A80] text-sm">error</span>
      <span class="text-xs font-mono text-[#FF8A80]">{{ error }}</span>
    </div>
    <!-- Warnings (non-blocking) -->
    <div v-if="prepareWarnings.length" class="mx-8 mt-2 bg-[#FBF8F3] border-l-2 border-[#FFE066] px-6 py-3 flex items-start gap-3 flex-shrink-0">
      <span class="material-symbols-outlined text-[#FFE066] text-sm mt-0.5">warning</span>
      <div>
        <div v-for="w in prepareWarnings" :key="w" class="text-xs font-mono text-[#FFE066]">{{ w }}</div>
      </div>
    </div>

    <div class="flex flex-1 overflow-hidden">
      <!-- === SETUP TAB === -->
      <section v-if="activeTab === 'Setup'" class="flex-1 p-8 overflow-y-auto">
        <div v-if="!store.campaignId" class="bg-[#FBF8F3] border-l-2 border-[#FFE066] px-6 py-4 mb-6 flex items-center gap-3">
          <span class="material-symbols-outlined text-[#FFE066]">info</span>
          <span class="text-xs font-mono text-[#FFE066]">Upload a campaign first.</span>
          <router-link to="/campaign" class="ml-auto text-[10px] font-mono text-[#66BB6A] border border-[#66BB6A]/30 px-3 py-1">GO TO CAMPAIGN</router-link>
        </div>

        <!-- ── INPUT CONTROLS ── -->
        <h2 class="text-xl font-semibold text-[#2D2D2D] mb-6">Simulation Setup</h2>
        <div class="space-y-6 max-w-3xl">
          <div class="flex items-end gap-8">
            <div>
              <label class="font-mono text-[10px] text-[#6B6B6B] uppercase tracking-widest block mb-2">Number of Agents</label>
              <input v-model.number="numAgents" type="number" min="1" max="100"
                class="w-32 bg-[#FFFFFF] border border-[#E0DDD5] px-4 py-2 text-[#2D2D2D] font-mono text-sm focus:ring-1 focus:ring-[#66BB6A]" />
            </div>
            <div>
              <label class="font-mono text-[10px] text-[#6B6B6B] uppercase tracking-widest block mb-2">Number of Rounds</label>
              <div class="flex items-center gap-3">
                <input v-model.number="numRounds" type="range" min="1" max="100" step="1" class="w-48 accent-[#66BB6A]" />
                <input v-model.number="numRounds" type="number" min="1" max="100"
                  class="w-20 bg-[#FFFFFF] border border-[#E0DDD5] px-3 py-2 text-[#2D2D2D] font-mono text-sm focus:ring-1 focus:ring-[#66BB6A] text-center" />
              </div>
              <span class="text-[9px] font-mono text-[#6B6B6B] mt-1 block">Custom mode override</span>
            </div>
          </div>

          <!-- ── COGNITIVE PIPELINE ── -->
          <div class="mt-6 pt-4 border-t border-[#E0DDD5]">
            <div class="flex items-center gap-2 mb-4">
              <span class="material-symbols-outlined text-sm text-[#9B59B6]">neurology</span>
              <span class="font-mono text-[10px] text-[#6B6B6B] uppercase tracking-widest">Cognitive Pipeline</span>
              <span class="ml-auto text-[9px] font-mono text-[#9B9B9B]">{{ cognitiveToggles.filter(t => t.enabled).length }}/{{ cognitiveToggles.length }} active</span>
            </div>
            <div class="space-y-2">
              <div v-for="t in cognitiveToggles" :key="t.key"
                class="flex items-center gap-3 p-2.5 border-[1.5px] transition-all duration-200 cursor-pointer group"
                :class="t.enabled
                  ? 'border-[#66BB6A] bg-[#66BB6A]/5 hover:bg-[#66BB6A]/10'
                  : 'border-[#E0DDD5] bg-[#F5F0E8]/50 hover:bg-[#E0DDD5]/30'"
                @click="t.enabled = !t.enabled">
                <!-- Icon -->
                <div class="w-8 h-8 flex items-center justify-center flex-shrink-0 transition-colors duration-200 border-[1.5px] border-[#2D2D2D]"
                  :class="t.enabled ? 'bg-[#66BB6A]/15 text-[#66BB6A]' : 'bg-[#E0DDD5]/50 text-[#9B9B9B]'">
                  <span class="material-symbols-outlined text-base">{{ t.icon }}</span>
                </div>
                <!-- Label + Desc -->
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="text-xs font-semibold" :class="t.enabled ? 'text-[#2D2D2D]' : 'text-[#9B9B9B]'">{{ t.label }}</span>
                    <span class="text-[8px] font-mono px-1.5 py-0.5 rounded"
                      :class="t.enabled ? 'bg-[#66BB6A]/10 text-[#66BB6A]' : 'bg-[#E0DDD5]/50 text-[#9B9B9B]'">
                      {{ t.enabled ? 'ON' : 'OFF' }}
                    </span>
                  </div>
                  <span class="text-[10px] leading-tight block mt-0.5" :class="t.enabled ? 'text-[#6B6B6B]' : 'text-[#B5B0A8]'">{{ t.desc }}</span>
                </div>
                <!-- Toggle switch (Memphis square) -->
                <div class="relative w-10 h-[22px] flex-shrink-0 transition-colors duration-200 border-[1.5px] border-[#2D2D2D]"
                  :class="t.enabled ? 'bg-[#66BB6A]' : 'bg-[#E0DDD5]'">
                  <div class="absolute top-[2px] w-[14px] h-[14px] bg-white border-[1.5px] border-[#2D2D2D] shadow-sm transition-transform duration-200"
                    :class="t.enabled ? 'translate-x-[20px]' : 'translate-x-[2px]'"></div>
                </div>
              </div>
            </div>
          </div>

          <!-- ── CRISIS INJECTION SETUP ── -->
          <div class="mt-6 pt-4 border-t border-[#E0DDD5]">
            <div class="flex items-center justify-between mb-4">
              <div class="flex items-center gap-2">
                <span class="material-symbols-outlined text-sm text-[#FF8A80]">crisis_alert</span>
                <span class="font-mono text-[10px] text-[#6B6B6B] uppercase tracking-widest">Crisis Injection</span>
              </div>
              <div class="flex items-center gap-2 cursor-pointer" @click="crisisEnabled = !crisisEnabled">
                <span class="text-[10px] font-mono" :class="crisisEnabled ? 'text-[#FF8A80]' : 'text-[#9B9B9B]'">
                  {{ crisisEnabled ? 'BẬT' : 'TẮT' }}
                </span>
                <div class="relative w-10 h-[22px] flex-shrink-0 transition-colors duration-200 border-[1.5px] border-[#2D2D2D]"
                  :class="crisisEnabled ? 'bg-[#FF8A80]' : 'bg-[#E0DDD5]'">
                  <div class="absolute top-[2px] w-[14px] h-[14px] bg-white border-[1.5px] border-[#2D2D2D] shadow-sm transition-transform duration-200"
                    :class="crisisEnabled ? 'translate-x-[20px]' : 'translate-x-[2px]'"></div>
                </div>
              </div>
            </div>

            <!-- Crisis Config (shown when enabled) -->
            <div v-if="crisisEnabled" class="space-y-4 pl-1">
              <!-- Crisis List -->
              <div v-for="(crisis, ci) in crisisEvents" :key="ci"
                class="p-4 border-[1.5px] transition-all duration-200"
                :class="crisis.mode === 'scheduled' ? 'border-[#FFE066] bg-[#FFE066]/5' : 'border-[#FF8A80] bg-[#FF8A80]/5'">
                <div class="flex items-start justify-between mb-3">
                  <div class="flex items-center gap-2">
                    <span class="text-sm">{{ crisis.mode === 'scheduled' ? '⏰' : '⚡' }}</span>
                    <span class="text-xs font-bold text-[#2D2D2D]">Crisis #{{ ci + 1 }}</span>
                    <span class="px-1.5 py-0.5 text-[8px] font-mono uppercase border"
                      :class="crisis.mode === 'scheduled'
                        ? 'border-[#FFE066] text-[#FFE066] bg-[#FFE066]/10'
                        : 'border-[#FF8A80] text-[#FF8A80] bg-[#FF8A80]/10'">
                      {{ crisis.mode === 'scheduled' ? 'Hẹn giờ' : 'Trực tiếp' }}
                    </span>
                  </div>
                  <button @click="removeCrisis(ci)" class="text-[#FF8A80] hover:text-red-600 transition-colors">
                    <span class="material-symbols-outlined text-sm">close</span>
                  </button>
                </div>

                <!-- Title -->
                <div class="mb-2">
                  <label class="font-mono text-[9px] text-[#6B6B6B] uppercase tracking-widest block mb-1">Tên khủng hoảng *</label>
                  <input v-model="crisis.title" type="text"
                    placeholder="VD: Shopee tăng giá 30%, Scandal CEO..."
                    class="w-full bg-[#FFFFFF] border border-[#E0DDD5] px-3 py-2 text-[#2D2D2D] font-mono text-xs focus:ring-1 focus:ring-[#FF8A80] focus:border-[#FF8A80]" />
                </div>

                <!-- Description -->
                <div class="mb-2">
                  <label class="font-mono text-[9px] text-[#6B6B6B] uppercase tracking-widest block mb-1">Mô tả</label>
                  <textarea v-model="crisis.description" rows="2"
                    placeholder="Mô tả chi tiết về sự kiện khủng hoảng..."
                    class="w-full bg-[#FFFFFF] border border-[#E0DDD5] px-3 py-2 text-[#2D2D2D] text-xs focus:ring-1 focus:ring-[#FF8A80] focus:border-[#FF8A80] resize-none"></textarea>
                </div>

                <!-- Injection Mode -->
                <div class="mb-2">
                  <label class="font-mono text-[9px] text-[#6B6B6B] uppercase tracking-widest block mb-1">Phương thức</label>
                  <div class="flex gap-2">
                    <button @click="crisis.mode = 'scheduled'"
                      class="flex-1 py-2 text-[10px] font-mono font-bold border-2 transition-all flex items-center justify-center gap-1.5"
                      :class="crisis.mode === 'scheduled'
                        ? 'border-[#FFE066] bg-[#FFE066]/10 text-[#2D2D2D]'
                        : 'border-[#E0DDD5] text-[#9B9B9B] hover:border-[#FFE066]'">
                      ⏰ Hẹn theo Round
                    </button>
                    <button @click="crisis.mode = 'realtime'"
                      class="flex-1 py-2 text-[10px] font-mono font-bold border-2 transition-all flex items-center justify-center gap-1.5"
                      :class="crisis.mode === 'realtime'
                        ? 'border-[#FF8A80] bg-[#FF8A80]/10 text-[#2D2D2D]'
                        : 'border-[#E0DDD5] text-[#9B9B9B] hover:border-[#FF8A80]'">
                      ⚡ Thêm trực tiếp
                    </button>
                  </div>
                </div>

                <!-- Scheduled: Round number -->
                <div v-if="crisis.mode === 'scheduled'" class="mb-2">
                  <label class="font-mono text-[9px] text-[#6B6B6B] uppercase tracking-widest block mb-1">Kích hoạt tại Round</label>
                  <div class="flex items-center gap-3">
                    <input v-model.number="crisis.trigger_round" type="range" :min="1" :max="numRounds" step="1" class="flex-1 accent-[#FFE066]" />
                    <input v-model.number="crisis.trigger_round" type="number" :min="1" :max="numRounds"
                      class="w-16 bg-[#FFFFFF] border border-[#E0DDD5] px-2 py-1.5 text-center text-[#2D2D2D] font-mono text-xs focus:ring-1 focus:ring-[#FFE066]" />
                    <span class="text-[9px] font-mono text-[#6B6B6B]">/ {{ numRounds }}</span>
                  </div>
                </div>

                <!-- Realtime: Info -->
                <div v-if="crisis.mode === 'realtime'" class="p-2 bg-[#FF8A80]/5 border border-[#FF8A80]/20">
                  <p class="text-[10px] text-[#6B6B6B] leading-relaxed">
                    💡 Khủng hoảng này sẽ được inject <strong>thủ công</strong> khi simulation đang chạy.
                    Bạn sẽ thấy nút <strong>"⚡ Inject"</strong> ở tab Run để kích hoạt.
                  </p>
                </div>

                <!-- Severity -->
                <div class="mt-2">
                  <div class="flex items-center justify-between mb-1">
                    <label class="font-mono text-[9px] text-[#6B6B6B] uppercase tracking-widest">Mức độ nghiêm trọng</label>
                    <span class="text-[10px] font-mono font-bold"
                      :class="crisis.severity > 0.7 ? 'text-[#FF8A80]' : crisis.severity > 0.4 ? 'text-[#FFE066]' : 'text-[#66BB6A]'">
                      {{ (crisis.severity * 100).toFixed(0) }}%
                    </span>
                  </div>
                  <input v-model.number="crisis.severity" type="range" min="0" max="1" step="0.05" class="w-full accent-[#FF8A80]" />
                </div>
              </div>

              <!-- Add Crisis Button -->
              <button @click="addCrisis"
                class="w-full py-2.5 border-2 border-dashed border-[#FF8A80]/40 text-[#FF8A80] hover:border-[#FF8A80] hover:bg-[#FF8A80]/5 transition-all flex items-center justify-center gap-2 text-xs font-mono font-bold">
                <span class="material-symbols-outlined text-sm">add</span>
                THÊM KHỦNG HOẢNG
              </button>

              <!-- Summary -->
              <div v-if="crisisEvents.length > 0" class="p-3 bg-[#FBF8F3] border border-[#E0DDD5]/30">
                <div class="flex items-center gap-2 mb-1">
                  <span class="material-symbols-outlined text-xs text-[#FF8A80]">summarize</span>
                  <span class="text-[9px] font-mono text-[#6B6B6B] uppercase">Tóm tắt Crisis</span>
                </div>
                <div class="text-[10px] text-[#6B6B6B] space-y-0.5">
                  <p>📊 Tổng: <strong>{{ crisisEvents.length }}</strong> khủng hoảng</p>
                  <p v-if="scheduledCrises.length">⏰ Hẹn giờ: <strong>{{ scheduledCrises.length }}</strong> (rounds: {{ scheduledCrises.map(c => c.trigger_round).join(', ') }})</p>
                  <p v-if="realtimeCrises.length">⚡ Trực tiếp: <strong>{{ realtimeCrises.length }}</strong> (inject thủ công lúc chạy)</p>
                </div>
              </div>
            </div>
          </div>

          <button @click="prepareSimulation" :disabled="preparing || !store.campaignId"
            class="mt-6 px-6 py-2.5 bg-[#66BB6A] text-[#F5F0E8] font-bold text-sm tracking-tight flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[#66BB6A]/90 transition-colors">
            <div v-if="preparing" class="w-4 h-4 border-2 border-[#F5F0E8] border-t-transparent rounded-full animate-spin"></div>
            <span class="material-symbols-outlined text-sm" v-else>play_arrow</span>
            {{ preparing ? 'PREPARING...' : 'PREPARE SIMULATION' }}
          </button>
        </div>

        <!-- ── STEP 02: AGENT PROFILES (Memphis) ── -->
        <div v-if="profiles.length" class="mt-10 max-w-5xl">
          <div class="flex items-center gap-3 mb-5">
            <div class="memphis-step">02</div>
            <h3 class="text-sm font-bold tracking-tight" style="font-family:'Space Grotesk',sans-serif">
              Agent Profiles
              <span class="ml-1 text-[#9B9B9B] font-normal">({{ profiles.length }})</span>
            </h3>
            <span class="memphis-tag memphis-tag-green" style="font-size:0.55rem">✓ Complete</span>
          </div>
          <div class="grid grid-cols-1 gap-5 max-h-[650px] overflow-y-auto pr-2">
            <div v-for="(p, idx) in profiles" :key="p.agent_id ?? idx" class="agent-card">

              <!-- Row 1: Identity -->
              <div class="flex items-start justify-between mb-3">
                <div class="flex items-center gap-3">
                  <!-- Avatar: MBTI-coded geometric shape -->
                  <div class="agent-avatar" :class="getMbtiAvatarClass(p.mbti)">
                    {{ (p.realname || p.name || '?').charAt(0).toUpperCase() }}
                  </div>
                  <div>
                    <div class="flex items-center gap-2">
                      <span class="text-base font-bold text-[#2D2D2D]" style="font-family:'Space Grotesk',sans-serif">{{ p.realname || p.name }}</span>
                      <span class="text-[10px] text-[#9B9B9B]" style="font-family:'Space Mono',monospace">@{{ p.username || p.handle }}</span>
                    </div>
                    <div class="flex items-center gap-1.5 mt-1">
                      <span v-if="p.mbti" class="memphis-tag memphis-tag-lilac">{{ p.mbti }}</span>
                      <span v-if="p.entity_type || p.role" class="memphis-tag memphis-tag-green">{{ p.entity_type || p.role }}</span>
                      <span v-if="p.stance_label" class="memphis-tag"
                        :class="p.stance_label === 'supportive' ? 'memphis-tag-mint' : p.stance_label === 'opposing' ? 'memphis-tag-pink' : ''">
                        {{ p.stance_label }}
                      </span>
                    </div>
                  </div>
                </div>
                <!-- Follower counter -->
                <div v-if="p.follower_count" class="text-right flex-shrink-0">
                  <span class="stat-block-label">followers</span>
                  <span class="text-lg font-bold" style="font-family:'Space Mono',monospace; color:#9B59B6">
                    {{ p.follower_count >= 1000 ? (p.follower_count / 1000).toFixed(1) + 'K' : p.follower_count }}
                  </span>
                </div>
              </div>

              <!-- Row 2: Demographics -->
              <div class="flex flex-wrap items-center gap-3 mb-3 ml-[56px]">
                <span v-if="p.age" class="flex items-center gap-1 text-[11px] text-[#6B6B6B]" style="font-family:'DM Sans',sans-serif">
                  <span class="material-symbols-outlined" style="font-size:14px; color:#FFE066">cake</span>
                  {{ p.age }} tuổi
                </span>
                <span v-if="p.gender && p.gender !== 'other'" class="flex items-center gap-1 text-[11px] text-[#6B6B6B]">
                  <span class="material-symbols-outlined" style="font-size:14px; color:#FFB7B2">{{ p.gender === 'male' ? 'male' : 'female' }}</span>
                  {{ p.gender }}
                </span>
                <span v-if="p.gender === 'other'" class="flex items-center gap-1 text-[11px] text-[#6B6B6B]">
                  <span class="material-symbols-outlined" style="font-size:14px; color:#B5E8F0">business</span>
                  organization
                </span>
                <span v-if="p.country" class="flex items-center gap-1 text-[11px] text-[#6B6B6B]">
                  <span class="material-symbols-outlined" style="font-size:14px; color:#A8E6CF">location_on</span>
                  {{ p.country }}
                </span>
                <span v-if="p.profession" class="flex items-center gap-1 text-[11px] text-[#FFE066]">
                  <span class="material-symbols-outlined" style="font-size:14px">work</span>
                  {{ p.profession }}
                </span>
              </div>

              <!-- Row 3: Bio -->
              <p v-if="p.bio" class="text-xs text-[#2D2D2D] leading-relaxed mb-3 ml-[56px] font-medium" style="font-family:'DM Sans',sans-serif; max-width:60ch">{{ p.bio }}</p>

              <!-- Row 4: Persona (truncated, expandable) -->
              <div v-if="p.user_char || p.persona" class="ml-[56px] mb-3">
                <p class="text-[11px] text-[#6B6B6B] leading-relaxed" style="font-family:'DM Sans',sans-serif">
                  {{ expandedProfiles.has(p.agent_id)
                    ? (p.user_char || p.persona)
                    : (p.user_char || p.persona || '').slice(0, 200) + ((p.user_char || p.persona || '').length > 200 ? '...' : '')
                  }}
                </p>
                <button v-if="(p.user_char || p.persona || '').length > 200"
                  @click="toggleProfile(p.agent_id)"
                  class="expand-btn mt-1.5">
                  {{ expandedProfiles.has(p.agent_id) ? '▲ Thu gọn' : '▼ Xem đầy đủ' }}
                </button>
              </div>

              <!-- Row 5: Topics -->
              <div v-if="p.topics?.length" class="ml-[56px] mb-3 flex flex-wrap gap-1.5">
                <span v-for="t in p.topics.slice(0, 5)" :key="t" class="memphis-tag memphis-tag-peach">#{{ t }}</span>
              </div>

              <!-- Row 5b: Initial Interests -->
              <div v-if="getInitialInterests(p).length" class="ml-[56px] mb-3">
                <span class="stat-block-label block mb-1.5">Sở thích ban đầu</span>
                <div class="flex flex-wrap gap-1.5">
                  <span v-for="int in getInitialInterests(p)" :key="int" class="interest-pill">
                    <span class="material-symbols-outlined" style="font-size:10px">push_pin</span> {{ int }}
                  </span>
                </div>
              </div>

              <!-- Memphis divider -->
              <div class="memphis-divider ml-[56px]"></div>

              <!-- Row 6: Behavior stats -->
              <div class="ml-[56px] grid grid-cols-6 gap-2">
                <div class="stat-block">
                  <span class="stat-block-label">Posts</span>
                  <span class="stat-block-value">{{ p.posting_probability != null ? p.posting_probability.toFixed(1) : '—' }}</span>
                </div>
                <div class="stat-block">
                  <span class="stat-block-label">Comments</span>
                  <span class="stat-block-value">{{ p.comments_per_time != null ? p.comments_per_time.toFixed(1) : '—' }}</span>
                </div>
                <div class="stat-block">
                  <span class="stat-block-label">Delay</span>
                  <span class="stat-block-value">{{ p.response_delay_label || '—' }}</span>
                </div>
                <div class="stat-block">
                  <span class="stat-block-label">Activity</span>
                  <span class="stat-block-value" style="color:#9B59B6">{{ p.activity_level != null ? (p.activity_level * 100).toFixed(0) + '%' : '—' }}</span>
                </div>
                <div class="stat-block">
                  <span class="stat-block-label">Sentiment</span>
                  <span class="stat-block-value"
                    :style="{ color: p.sentiment_bias > 0.1 ? '#66BB6A' : p.sentiment_bias < -0.1 ? '#FF8A80' : '#FFC107' }">
                    {{ p.sentiment_bias != null ? (p.sentiment_bias > 0 ? '+' : '') + p.sentiment_bias.toFixed(1) : '—' }}
                  </span>
                </div>
                <div class="stat-block">
                  <span class="stat-block-label">Influence</span>
                  <span class="stat-block-value" style="color:#0097A7">{{ p.influence_score != null ? p.influence_score.toFixed(1) : '—' }}</span>
                </div>
              </div>

              <!-- Row 7: Cognitive Traits (visual bars) -->
              <div v-if="p.mbti" class="ml-[56px] mt-3 pt-3 border-t-[2px] border-[#E0DDD5]">
                <div class="flex items-center gap-2 mb-2.5">
                  <span class="material-symbols-outlined" style="font-size:16px; color:#9B59B6">neurology</span>
                  <span class="stat-block-label" style="margin-bottom:0">Nhận thức tính cách</span>
                </div>
                <div class="grid grid-cols-4 gap-3">
                  <div>
                    <div class="flex items-center justify-between mb-1">
                      <span class="text-[8px] font-bold text-[#6B6B6B] uppercase" style="font-family:'Space Grotesk',sans-serif">Bảo thủ</span>
                      <span class="text-[9px] font-bold" style="font-family:'Space Mono',monospace"
                        :style="{ color: getCogTraits(p.mbti).conviction >= 0.7 ? '#FF8A80' : getCogTraits(p.mbti).conviction <= 0.4 ? '#66BB6A' : '#FFC107' }">
                        {{ getCogTraits(p.mbti).conviction.toFixed(2) }}
                      </span>
                    </div>
                    <div class="trait-bar-track">
                      <div class="trait-bar-fill fill-coral" :style="{ width: (getCogTraits(p.mbti).conviction * 100) + '%' }"></div>
                    </div>
                  </div>
                  <div>
                    <div class="flex items-center justify-between mb-1">
                      <span class="text-[8px] font-bold text-[#6B6B6B] uppercase" style="font-family:'Space Grotesk',sans-serif">Hay quên</span>
                      <span class="text-[9px] font-bold" style="font-family:'Space Mono',monospace"
                        :style="{ color: getCogTraits(p.mbti).forgetfulness >= 0.2 ? '#FF8A80' : getCogTraits(p.mbti).forgetfulness <= 0.1 ? '#66BB6A' : '#FFC107' }">
                        {{ getCogTraits(p.mbti).forgetfulness.toFixed(2) }}
                      </span>
                    </div>
                    <div class="trait-bar-track">
                      <div class="trait-bar-fill fill-yellow" :style="{ width: (getCogTraits(p.mbti).forgetfulness * 100) + '%' }"></div>
                    </div>
                  </div>
                  <div>
                    <div class="flex items-center justify-between mb-1">
                      <span class="text-[8px] font-bold text-[#6B6B6B] uppercase" style="font-family:'Space Grotesk',sans-serif">Tò mò</span>
                      <span class="text-[9px] font-bold" style="font-family:'Space Mono',monospace"
                        :style="{ color: getCogTraits(p.mbti).curiosity >= 0.4 ? '#66BB6A' : getCogTraits(p.mbti).curiosity <= 0.2 ? '#FF8A80' : '#FFC107' }">
                        {{ getCogTraits(p.mbti).curiosity.toFixed(2) }}
                      </span>
                    </div>
                    <div class="trait-bar-track">
                      <div class="trait-bar-fill fill-green" :style="{ width: (getCogTraits(p.mbti).curiosity * 100) + '%' }"></div>
                    </div>
                  </div>
                  <div>
                    <div class="flex items-center justify-between mb-1">
                      <span class="text-[8px] font-bold text-[#6B6B6B] uppercase" style="font-family:'Space Grotesk',sans-serif">Dễ ảnh hưởng</span>
                      <span class="text-[9px] font-bold" style="font-family:'Space Mono',monospace"
                        :style="{ color: getCogTraits(p.mbti).impressionability >= 0.2 ? '#FF8A80' : getCogTraits(p.mbti).impressionability <= 0.1 ? '#66BB6A' : '#FFC107' }">
                        {{ getCogTraits(p.mbti).impressionability.toFixed(2) }}
                      </span>
                    </div>
                    <div class="trait-bar-track">
                      <div class="trait-bar-fill fill-lilac" :style="{ width: (getCogTraits(p.mbti).impressionability * 100) + '%' }"></div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ── STEP 03: START ── -->
        <div v-if="simReady" class="mt-10 max-w-3xl">
          <div class="flex items-center gap-3 mb-4">
            <span class="px-2 py-0.5 bg-[#66BB6A]/10 text-[#66BB6A] text-[10px] font-mono border border-[#66BB6A]/20">03</span>
            <h3 class="font-mono text-xs text-[#6B6B6B] uppercase tracking-widest">Ready to Launch</h3>
          </div>
          <div class="bg-[#FFFFFF] border border-[#E0DDD5]/30 p-6">
            <div class="grid grid-cols-2 gap-4 mb-6 text-center">
              <div>
                <span class="text-[9px] font-mono text-[#6B6B6B] uppercase block">Agents</span>
                <span class="text-2xl font-mono text-[#66BB6A]">{{ profiles.length }}</span>
              </div>
              <div>
                <span class="text-[9px] font-mono text-[#6B6B6B] uppercase block">Rounds</span>
                <span class="text-2xl font-mono text-[#2D2D2D]">{{ numRounds }}</span>
              </div>
            </div>
            <button @click="startSimulation"
              class="w-full py-3 bg-[#66BB6A] text-[#F5F0E8] font-bold text-sm tracking-tight flex items-center justify-center gap-2 hover:bg-[#66BB6A]/90 transition-colors">
              <span class="material-symbols-outlined text-sm">rocket_launch</span>
              START SIMULATION
            </button>
          </div>
        </div>
      </section>

      <!-- === RUN TAB === -->
      <section v-if="activeTab === 'Run'" class="flex-1 flex flex-col p-8 overflow-y-auto">
        <!-- Status Header -->
        <div class="mb-6">
          <div class="flex justify-between items-end mb-3">
            <div class="flex items-center gap-3">
              <span v-if="simStatus === 'running'" class="w-2.5 h-2.5 rounded-full bg-[#66BB6A] animate-pulse"></span>
              <span v-else-if="simStatus === 'completed'" class="w-2.5 h-2.5 rounded-full bg-[#66BB6A]"></span>
              <span v-else-if="simStatus === 'failed'" class="w-2.5 h-2.5 rounded-full bg-[#FF8A80]"></span>
              <span v-else class="w-2.5 h-2.5 rounded-full bg-[#6B6B6B]"></span>
              <h2 class="text-xl font-sans font-semibold text-[#2D2D2D]">
                <template v-if="simStatus === 'running'">Đang chạy... Round <span class="font-mono text-[#66BB6A]">{{ progress.current_round }}/{{ progress.total_rounds }}</span></template>
                <template v-else-if="simStatus === 'completed'">
                  <span class="text-[#66BB6A]">Hoàn thành</span>
                </template>
                <template v-else-if="simStatus === 'failed'">
                  <span class="text-[#FF8A80]">Thất bại</span>
                </template>
                <template v-else>Chưa chạy</template>
              </h2>
            </div>
          </div>
          <!-- Progress bar -->
          <div class="w-full h-1.5 bg-[#E0DDD5] rounded-full overflow-hidden">
            <div class="h-full rounded-full transition-all duration-500 ease-out"
              :class="simStatus === 'failed' ? 'bg-[#FF8A80]' : 'bg-gradient-to-r from-[#66BB6A] to-[#B5E8F0]'"
              :style="{ width: progressPct + '%' }"></div>
          </div>
        </div>

        <!-- Real-time Crisis Inject -->
        <div v-if="simStatus === 'running' && realtimeCrises.length > 0" class="mb-4">
          <div class="flex items-center gap-2 mb-2">
            <span class="material-symbols-outlined text-sm text-[#FF8A80]">crisis_alert</span>
            <span class="text-[10px] font-mono font-bold text-[#6B6B6B] uppercase tracking-wider">Crisis trực tiếp</span>
          </div>
          <div class="flex flex-wrap gap-2">
            <button v-for="(c, ci) in realtimeCrises" :key="ci"
              @click="injectRealtimeCrisis(c)"
              :disabled="c._injected"
              class="px-3 py-1.5 text-[10px] font-mono font-bold border-2 flex items-center gap-1.5 transition-all"
              :class="c._injected
                ? 'border-[#66BB6A] bg-[#66BB6A]/10 text-[#66BB6A] cursor-default'
                : 'border-[#FF8A80] bg-[#FF8A80]/10 text-[#FF8A80] hover:bg-[#FF8A80]/20 cursor-pointer'">
              <span>{{ c._injected ? '✅' : '⚡' }}</span>
              {{ c.title || 'Crisis ' + (ci+1) }}
              <span v-if="c._injected" class="text-[8px]">(đã inject)</span>
            </button>
          </div>
        </div>

        <!-- Live Events Log (SSE) -->
        <div v-if="liveEvents.length" class="mb-6">
          <div class="flex items-center gap-2 mb-2">
            <span v-if="simStatus === 'running'" class="w-2 h-2 rounded-full bg-[#66BB6A] animate-pulse"></span>
            <span v-else class="w-2 h-2 rounded-full bg-[#6B6B6B]"></span>
            <span class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-wider">Live Stream</span>
            <span class="text-[9px] font-mono text-[#555B6E]">({{ liveEvents.length }} events)</span>
          </div>
          <div class="bg-[#F5F0E8] border border-[#E0DDD5]/40 max-h-48 overflow-y-auto font-mono text-[10px]">
            <div v-for="(ev, i) in liveEvents.slice(0, 30)" :key="i"
              class="px-3 py-1.5 border-b border-[#E0DDD5]/20 flex items-center gap-3">
              <span class="text-[#555B6E] w-20 flex-shrink-0">{{ ev.timestamp }}</span>
              <span v-if="ev.event === 'round_start'" class="px-1.5 py-0.5 bg-[#66BB6A]/10 text-[#66BB6A] text-[9px] flex-shrink-0">R{{ ev.round }}</span>
              <span v-else-if="ev.event === 'post'" class="px-1.5 py-0.5 bg-[#B5E8F0]/10 text-[#B5E8F0] text-[9px] flex-shrink-0">POST</span>
              <span v-else-if="ev.event === 'comment'" class="px-1.5 py-0.5 bg-[#D5C4F7]/10 text-[#D5C4F7] text-[9px] flex-shrink-0">CMT</span>
              <span v-else-if="ev.event === 'like'" class="px-1.5 py-0.5 bg-[#E85D75]/10 text-[#E85D75] text-[9px] flex-shrink-0">LIKE</span>
              <span v-else-if="ev.event === 'round_actions'" class="px-1.5 py-0.5 bg-[#FFE066]/10 text-[#FFE066] text-[9px] flex-shrink-0">SUM</span>
              <span v-else class="px-1.5 py-0.5 bg-[#6B6B6B]/10 text-[#6B6B6B] text-[9px] flex-shrink-0">{{ ev.event }}</span>
              <span class="text-[#6B6B6B] truncate">
                <template v-if="ev.event === 'round_start'">Round {{ ev.round }}/{{ ev.total_rounds }}</template>
                <template v-else>{{ ev.message }}</template>
              </span>
            </div>
          </div>
        </div>

        <!-- Quick Stats Row -->
        <div v-if="filteredActions.length" class="grid grid-cols-5 gap-3 mb-6">
          <div class="bg-[#FFFFFF] border border-[#E0DDD5]/40 px-4 py-3 flex flex-col items-center">
            <span class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-wider mb-1">Tổng</span>
            <span class="text-xl font-mono text-[#2D2D2D] font-bold">{{ filteredActions.length }}</span>
          </div>
          <div class="bg-[#FFFFFF] border border-[#E0DDD5]/40 px-4 py-3 flex flex-col items-center">
            <span class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-wider mb-1">Bài viết</span>
            <span class="text-xl font-mono text-[#B5E8F0] font-bold">{{ actionStats.posts }}</span>
          </div>
          <div class="bg-[#FFFFFF] border border-[#E0DDD5]/40 px-4 py-3 flex flex-col items-center">
            <span class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-wider mb-1">Bình luận</span>
            <span class="text-xl font-mono text-[#D5C4F7] font-bold">{{ actionStats.comments }}</span>
          </div>
          <div class="bg-[#FFFFFF] border border-[#E0DDD5]/40 px-4 py-3 flex flex-col items-center">
            <span class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-wider mb-1">Thích</span>
            <span class="text-xl font-mono text-[#E85D75] font-bold">{{ actionStats.likes }}</span>
          </div>
          <div class="bg-[#FFFFFF] border border-[#E0DDD5]/40 px-4 py-3 flex flex-col items-center">
            <span class="text-[9px] font-mono text-[#6B6B6B] uppercase tracking-wider mb-1">Agent</span>
            <span class="text-xl font-mono text-[#66BB6A] font-bold">{{ actionStats.uniqueAgents }}</span>
          </div>
        </div>

        <!-- Empty State -->
        <div v-if="filteredActions.length === 0" class="flex-1 flex items-center justify-center">
          <div class="flex flex-col items-center gap-4 text-[#6B6B6B]">
            <div class="w-16 h-16 rounded-full bg-[#FBF8F3] flex items-center justify-center">
              <span class="material-symbols-outlined text-3xl text-[#E0DDD5]">forum</span>
            </div>
            <p class="font-mono text-xs">Chưa có hoạt động. Bắt đầu mô phỏng từ tab Setup.</p>
          </div>
        </div>

        <!-- Activity Feed (Reddit-style) -->
        <div v-else class="flex flex-col gap-3 max-w-4xl">
          <template v-for="(entry, i) in postActions" :key="'post-' + i">
            <!-- POST CARD -->
            <div class="bg-[#FFFFFF] border border-[#E0DDD5]/40 rounded-lg overflow-hidden hover:border-[#E0DDD5]/70 transition-all duration-200">
              <!-- Post Header -->
              <div class="px-5 pt-4 pb-2 flex items-center gap-3">
                <div class="w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-bold bg-gradient-to-br from-[#B5E8F0] to-[#D5C4F7] text-white">
                  {{ (entry.agent_name || '?').charAt(0).toUpperCase() }}
                </div>
                <div class="flex flex-col">
                  <div class="flex items-center gap-2">
                    <span class="text-sm font-sans font-semibold text-[#2D2D2D]">{{ entry.agent_name || 'Unknown' }}</span>
                    <span class="text-[9px] font-mono text-[#555B6E]">•</span>
                    <span class="text-[10px] font-mono text-[#555B6E]">{{ formatTimestamp(entry.timestamp) }}</span>
                  </div>
                  <span class="text-[10px] font-mono text-[#555B6E]">u/{{ (entry.agent_name || 'unknown').replace(/\s+/g, '_') }}</span>
                </div>
              </div>
              <!-- Post Content -->
              <div class="px-5 pb-3">
                <p class="text-[14px] text-[#D0D5E0] leading-relaxed whitespace-pre-wrap">{{ entry.content }}</p>
              </div>
              <!-- Engagement Bar (Reddit-style) -->
              <div class="px-5 pb-3 flex items-center gap-5 text-[#6B6B6B]">
                <div class="flex items-center gap-1.5 text-[11px] font-mono">
                  <span class="text-[#E85D75]">▲</span>
                  <span class="text-[#2D2D2D] font-semibold">{{ entry.num_likes || 0 }}</span>
                  <span class="text-[#555B6E]">▼</span>
                  <span v-if="entry.num_dislikes > 0" class="text-[#555B6E] ml-0.5">{{ entry.num_dislikes }}</span>
                </div>
                <div class="flex items-center gap-1.5 text-[11px] font-mono cursor-pointer hover:text-[#D5C4F7] transition-colors"
                  @click="toggleComments(entry.post_id)">
                  <span class="material-symbols-outlined text-sm">chat_bubble_outline</span>
                  <span>{{ entry.num_comments || 0 }} Bình luận</span>
                </div>
                <div class="flex items-center gap-1.5 text-[11px] font-mono cursor-pointer hover:text-[#66BB6A] transition-colors">
                  <span class="material-symbols-outlined text-sm">share</span>
                  <span>Chia sẻ</span>
                </div>
              </div>
              <!-- Threaded Comments -->
              <div v-if="entry.comments?.length && expandedComments.has(entry.post_id)"
                class="border-t border-[#E0DDD5]/50 bg-[#141820] px-5 py-3">
                <div v-for="(comment, ci) in entry.comments" :key="ci"
                  class="flex gap-3 py-2.5" :class="ci < entry.comments.length - 1 ? 'border-b border-[#E0DDD5]/20' : ''">
                  <!-- Thread line + Avatar -->
                  <div class="flex flex-col items-center gap-1 flex-shrink-0">
                    <div class="w-6 h-6 rounded-full flex items-center justify-center text-[9px] font-bold bg-[#E0DDD5] text-[#D5C4F7]">
                      {{ (comment.agent_name || '?').charAt(0).toUpperCase() }}
                    </div>
                    <div v-if="ci < entry.comments.length - 1" class="w-px flex-1 bg-[#E0DDD5]/50"></div>
                  </div>
                  <!-- Comment content -->
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-0.5">
                      <span class="text-[12px] font-sans font-semibold text-[#C4CAD6]">{{ comment.agent_name }}</span>
                      <span class="text-[9px] font-mono text-[#555B6E]">•</span>
                      <span class="text-[9px] font-mono text-[#555B6E]">{{ formatTimestamp(comment.timestamp) }}</span>
                    </div>
                    <p class="text-[12px] text-[#6B6B6B] leading-relaxed">{{ comment.content }}</p>
                  </div>
                </div>
              </div>
              <!-- "Show comments" collapsed hint -->
              <div v-else-if="entry.num_comments > 0 && !expandedComments.has(entry.post_id)"
                @click="toggleComments(entry.post_id)"
                class="border-t border-[#E0DDD5]/30 bg-[#141820] px-5 py-2 text-[11px] font-mono text-[#D5C4F7] cursor-pointer hover:text-[#A78BFA] transition-colors flex items-center gap-2">
                <span class="material-symbols-outlined text-sm">expand_more</span>
                Xem {{ entry.num_comments }} bình luận...
              </div>
            </div>
          </template>


          <!-- Likes are displayed as num_likes on each post card, no standalone entries -->
        </div>

        <!-- Bottom Actions -->
        <div class="mt-6 pt-4 flex gap-4 flex-shrink-0 border-t border-[#E0DDD5]" v-if="simStatus === 'completed' || simStatus === 'failed'">
          <button v-if="simStatus === 'completed'" @click="$router.push('/report')"
            class="px-6 py-2.5 bg-[#66BB6A] text-[#F5F0E8] text-xs font-bold hover:bg-[#66BB6A]/90 transition-colors flex items-center gap-2">
            <span class="material-symbols-outlined text-sm">bar_chart</span>
            Tạo báo cáo
          </button>
          <button v-if="simStatus === 'completed'" @click="$router.push('/survey')"
            class="px-6 py-2.5 bg-transparent border border-[#66BB6A]/30 text-[#66BB6A] text-xs font-bold hover:bg-[#66BB6A]/10 transition-colors flex items-center gap-2">
            <span class="material-symbols-outlined text-sm">quiz</span>
            Khảo sát Agent
          </button>
        </div>
      </section>

      <!-- === MONITOR TAB === -->
      <section v-if="activeTab === 'Monitor'" class="flex-1 p-8 overflow-y-auto">
        <!-- Header -->
        <div class="flex items-center justify-between mb-6">
          <div class="flex items-center gap-3">
            <span class="material-symbols-outlined text-[#9B59B6]">neurology</span>
            <h2 class="text-xl font-semibold text-[#2D2D2D]">Agent Cognitive Monitor</h2>
          </div>
          <!-- Agent Selector -->
          <div class="flex items-center gap-3">
            <select v-model="monitorAgentId" @change="loadMonitorData"
              class="text-xs font-mono px-3 py-1.5 bg-white border border-[#E0DDD5] text-[#2D2D2D] focus:border-[#9B59B6] outline-none">
              <option value="">— Chọn Agent —</option>
              <option v-for="p in profiles" :key="p.agent_id ?? profiles.indexOf(p)" :value="p.agent_id ?? profiles.indexOf(p)">
                {{ p.realname || p.name || `Agent ${p.agent_id ?? profiles.indexOf(p)}` }} ({{ p.mbti || '—' }})
              </option>
            </select>
            <button v-if="monitorAgentId !== ''" @click="loadMonitorData"
              class="text-[9px] font-mono text-[#66BB6A] border border-[#66BB6A]/30 px-2 py-1 hover:bg-[#66BB6A]/10 transition-colors">
              ↻ Refresh
            </button>
          </div>
        </div>

        <!-- Empty State -->
        <div v-if="monitorAgentId === ''" class="flex flex-col items-center justify-center h-[400px] text-[#6B6B6B]">
          <span class="material-symbols-outlined text-5xl text-[#E0DDD5] mb-3">person_search</span>
          <p class="text-sm font-mono">Chọn agent để theo dõi cognitive evolution</p>
          <p class="text-xs text-[#9B9B9B] mt-1">Yêu cầu: chạy simulation với cognitive toggles bật</p>
        </div>

        <!-- Monitor Loading -->
        <div v-else-if="monitorLoading" class="flex items-center justify-center h-[400px]">
          <div class="w-6 h-6 border-2 border-[#9B59B6] border-t-transparent rounded-full animate-spin"></div>
        </div>

        <!-- Monitor Error -->
        <div v-else-if="monitorError" class="bg-[#FF8A80]/10 border border-[#FF8A80]/30 p-4 text-sm text-[#FF8A80]">
          {{ monitorError }}
        </div>

        <!-- Monitor Data -->
        <div v-else-if="monitorData" class="space-y-4">
          <!-- Agent Info Banner -->
          <div class="p-4 bg-white border border-[#E0DDD5] flex items-center justify-between">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 bg-[#9B59B6]/10 border border-[#9B59B6]/30 flex items-center justify-center text-[#9B59B6] font-mono font-bold">
                {{ monitorData.agent.id }}
              </div>
              <div>
                <h3 class="text-sm font-bold text-[#2D2D2D]" style="font-family:'Space Mono',monospace">{{ monitorData.agent.name }}</h3>
                <div class="flex items-center gap-2 mt-0.5">
                  <span class="text-[10px] font-mono px-2 py-0.5 bg-[#B5E8F0]/20 text-[#0097A7] border border-[#B5E8F0]">MBTI: {{ monitorData.agent.mbti }}</span>
                  <span v-if="monitorData.profile?.entity_type" class="text-[10px] font-mono px-2 py-0.5 bg-[#66BB6A]/10 text-[#66BB6A] border border-[#66BB6A]/20">{{ monitorData.profile.entity_type }}</span>
                  <span v-if="monitorData.profile?.stance_label" class="text-[10px] font-mono px-2 py-0.5"
                    :class="monitorData.profile.stance_label === 'supportive' ? 'bg-[#66BB6A]/10 text-[#66BB6A]' : monitorData.profile.stance_label === 'opposing' ? 'bg-[#FF8A80]/10 text-[#FF8A80]' : 'bg-[#FFE066]/10 text-[#FFE066]'">{{ monitorData.profile.stance_label }}</span>
                </div>
              </div>
            </div>
            <div class="flex gap-4 text-center">
              <div v-if="monitorData.rounds?.length">
                <div class="text-lg font-mono font-bold text-[#9B59B6]">{{ monitorData.rounds[monitorData.rounds.length - 1]?.insights_count || 0 }}</div>
                <div class="text-[8px] font-mono text-[#6B6B6B] uppercase">insights</div>
              </div>
              <div v-if="monitorData.rounds?.length">
                <div class="text-lg font-mono font-bold text-[#FFE066]">{{ monitorData.rounds.reduce((s, r) => s + (r.actions?.length || 0), 0) }}</div>
                <div class="text-[8px] font-mono text-[#6B6B6B] uppercase">actions</div>
              </div>
              <div v-if="monitorData.status === 'profile_only'">
                <div class="text-[10px] font-mono text-[#FFE066] bg-[#FFE066]/10 px-2 py-1 border border-[#FFE066]/30">⏳ Chờ mô phỏng</div>
              </div>
            </div>
          </div>

          <!-- Profile Section (always shown) -->
          <div v-if="monitorData.profile" class="bg-white border border-[#E0DDD5] p-4 space-y-3">
            <div class="flex items-center gap-2 mb-2">
              <span class="material-symbols-outlined text-sm text-[#9B59B6]">person</span>
              <span class="font-mono text-[10px] text-[#6B6B6B] uppercase tracking-widest">Agent Profile</span>
            </div>
            <!-- Demographics -->
            <div class="flex flex-wrap items-center gap-3">
              <span v-if="monitorData.profile.age" class="text-[10px] font-mono text-[#6B6B6B]">🎂 {{ monitorData.profile.age }} tuổi</span>
              <span v-if="monitorData.profile.gender" class="text-[10px] font-mono text-[#6B6B6B]">{{ monitorData.profile.gender === 'male' ? '♂' : monitorData.profile.gender === 'female' ? '♀' : '🏢' }} {{ monitorData.profile.gender }}</span>
              <span v-if="monitorData.profile.profession" class="text-[10px] font-mono text-[#FFE066]">💼 {{ monitorData.profile.profession }}</span>
              <span v-if="monitorData.profile.country" class="text-[10px] font-mono text-[#6B6B6B]">📍 {{ monitorData.profile.country }}</span>
              <span v-if="monitorData.profile.follower_count" class="text-[10px] font-mono text-[#B5E8F0]">👥 {{ monitorData.profile.follower_count >= 1000 ? (monitorData.profile.follower_count/1000).toFixed(1)+'K' : monitorData.profile.follower_count }} followers</span>
              <span v-if="monitorData.profile.influence_score != null" class="text-[10px] font-mono text-[#D5C4F7]">⭐ {{ monitorData.profile.influence_score.toFixed(1) }} influence</span>
            </div>
            <!-- Bio -->
            <div v-if="monitorData.profile.bio">
              <span class="text-[8px] font-mono text-[#6B6B6B] uppercase block mb-0.5">Bio</span>
              <p class="text-xs text-[#2D2D2D] leading-relaxed">{{ monitorData.profile.bio }}</p>
            </div>
            <!-- Persona -->
            <div v-if="monitorData.profile.persona">
              <span class="text-[8px] font-mono text-[#6B6B6B] uppercase block mb-0.5">Persona</span>
              <pre class="text-[10px] text-[#2D2D2D] bg-[#F5F0E8] p-3 whitespace-pre-wrap font-mono max-h-[300px] overflow-y-auto leading-relaxed">{{ monitorData.profile.persona }}</pre>
            </div>
            <!-- Interests -->
            <div v-if="monitorData.profile.interests?.length">
              <span class="text-[8px] font-mono text-[#6B6B6B] uppercase block mb-1">Interests</span>
              <div class="flex flex-wrap gap-1">
                <span v-for="int in monitorData.profile.interests" :key="int"
                  class="text-[9px] font-mono px-2 py-0.5 bg-[#FFE066]/15 text-[#FF8F00] border border-[#FFE066]/30">{{ int }}</span>
              </div>
            </div>
          </div>

          <!-- Waiting for simulation notice -->
          <div v-if="monitorData.status === 'profile_only'" class="bg-[#FBF8F3] border-l-2 border-[#FFE066] px-4 py-3 flex items-center gap-2">
            <span class="material-symbols-outlined text-sm text-[#FFE066]">schedule</span>
            <span class="text-xs font-mono text-[#6B6B6B]">Chạy simulation để theo dõi cognitive evolution qua từng round</span>
          </div>

          <!-- Round Timeline -->
          <div v-for="(rd, idx) in monitorData.rounds" :key="rd.round"
            class="relative pl-6 border-l-2"
            :class="rd.insights_count > (idx > 0 ? monitorData.rounds[idx-1].insights_count : 0) ? 'border-[#9B59B6]' : 'border-[#E0DDD5]'">
            <!-- Timeline Dot -->
            <div class="absolute left-[-7px] top-3 w-3 h-3 rounded-full border-2 border-white"
              :class="rd.insights_count > (idx > 0 ? monitorData.rounds[idx-1].insights_count : 0) ? 'bg-[#9B59B6]' : 'bg-[#E0DDD5]'"></div>

            <div class="ml-3 mb-4 p-4 bg-white border border-[#E0DDD5] hover:border-[#9B59B6]/30 transition-colors">
              <!-- Round header -->
              <div class="flex items-center gap-2 mb-2">
                <span class="font-mono text-[10px] px-1.5 py-0.5 bg-[#F5F0E8] text-[#2D2D2D] font-bold">R{{ rd.round }}</span>
                <span v-if="rd.round === 0" class="text-[8px] font-mono text-[#66BB6A] bg-[#66BB6A]/10 px-1.5 py-0.5">INITIAL</span>
                <span v-if="rd.insights_count > (idx > 0 ? monitorData.rounds[idx-1].insights_count : 0)"
                  class="text-[8px] font-mono text-[#9B59B6] bg-[#9B59B6]/10 px-1.5 py-0.5">⭐ REFLECTION</span>
                <button @click="toggleMonitorExpand(rd.round)" class="ml-auto text-[8px] font-mono text-[#6B6B6B] hover:text-[#2D2D2D]">
                  {{ monitorExpanded.has(rd.round) ? '▼' : '▶' }}
                </button>
              </div>

              <!-- Compact: key info -->
              <div class="space-y-1.5">
                <!-- Reflection -->
                <div v-if="rd.reflections" class="bg-[#9B59B6]/5 border-l-2 border-[#9B59B6] px-2 py-1.5">
                  <p class="text-[10px] text-[#2D2D2D] leading-relaxed">{{ rd.reflections }}</p>
                </div>
                <!-- Actions -->
                <div v-if="rd.actions?.length" class="flex flex-wrap gap-1">
                  <span v-for="(a, ai) in rd.actions" :key="ai"
                    class="text-[9px] font-mono px-1.5 py-0.5 border bg-[#F5F0E8] text-[#6B6B6B] border-[#E0DDD5]">
                    {{ a.type === 'create_post' ? '📝' : a.type === 'create_comment' ? '💬' : '❤️' }} {{ a.type.replace('create_', '').replace('like_', '') }}
                  </span>
                </div>
                <!-- Drift -->
                <div v-if="rd.drift_keywords?.length" class="flex items-center gap-1 flex-wrap">
                  <span class="text-[8px] font-mono text-[#6B6B6B] uppercase">drift:</span>
                  <span v-for="kw in rd.drift_keywords" :key="kw"
                    class="text-[9px] font-mono px-1 py-0.5 bg-[#FFE066]/20 text-[#FF8F00] border border-[#FFE066]/30">{{ kw }}</span>
                </div>
              </div>

              <!-- Expanded detail -->
              <div v-if="monitorExpanded.has(rd.round)" class="mt-3 pt-2 border-t border-[#E0DDD5] space-y-2">
                <div v-if="rd.memory">
                  <span class="text-[8px] font-mono text-[#6B6B6B] uppercase block mb-0.5">Memory</span>
                  <pre class="text-[10px] text-[#2D2D2D] bg-[#F5F0E8] p-2 whitespace-pre-wrap font-mono">{{ rd.memory }}</pre>
                </div>
                <div v-if="rd.evolved_persona">
                  <span class="text-[8px] font-mono text-[#6B6B6B] uppercase block mb-0.5">Evolved Persona</span>
                  <pre class="text-[10px] text-[#2D2D2D] bg-[#F5F0E8] p-2 whitespace-pre-wrap font-mono max-h-[200px] overflow-y-auto">{{ rd.evolved_persona }}</pre>
                </div>
                <!-- Cognitive Traits (personality card) -->
                <div v-if="rd.cognitive_traits && Object.keys(rd.cognitive_traits).length">
                  <span class="text-[8px] font-mono text-[#6B6B6B] uppercase block mb-1">🧠 Tính cách nhận thức</span>
                  <div class="bg-[#F5F0E8] p-2 space-y-1.5 border border-[#E0DDD5]">
                    <div v-for="(trait, key) in rd.cognitive_traits" :key="key" class="flex items-center gap-2">
                      <span class="text-[9px] text-[#6B6B6B] w-[100px] truncate font-mono">{{ trait.label }}</span>
                      <div class="flex-1 h-[6px] bg-[#E0DDD5] rounded-full overflow-hidden">
                        <div class="h-full rounded-full transition-all duration-500"
                          :style="{ width: (trait.value * 100) + '%' }"
                          :class="{
                            'bg-[#0097A7]': trait.value >= 0.7,
                            'bg-[#FF8F00]': trait.value >= 0.4 && trait.value < 0.7,
                            'bg-[#6B6B6B]': trait.value < 0.4
                          }"></div>
                      </div>
                      <span class="text-[8px] font-mono text-[#6B6B6B] w-[28px] text-right">{{ trait.value.toFixed(2) }}</span>
                      <span class="text-[8px] text-[#999] w-[90px] truncate">{{ trait.description }}</span>
                    </div>
                  </div>
                </div>

                <!-- Interest Vector (weighted interests with bars) -->
                <div v-if="rd.interest_vector?.length">
                  <span class="text-[8px] font-mono text-[#6B6B6B] uppercase block mb-1">Interest Vector</span>
                  <div class="space-y-1">
                    <div v-for="(item, idx) in rd.interest_vector" :key="idx"
                      class="flex items-center gap-1.5 text-[9px] font-mono">
                      <span class="w-[14px]">{{ item.source === 'profile' ? '📌' : '🔄' }}</span>
                      <span class="w-[100px] truncate"
                        :class="item.source === 'profile' ? 'text-[#0097A7]' : 'text-[#FF8F00]'"
                        :title="item.keyword">{{ item.keyword }}</span>
                      <div class="flex-1 h-[5px] bg-[#E0DDD5] rounded-full overflow-hidden">
                        <div class="h-full rounded-full transition-all duration-500"
                          :style="{ width: (item.weight * 100) + '%' }"
                          :class="{
                            'bg-[#0097A7]': item.source === 'profile',
                            'bg-[#FF8F00]': item.source === 'drift',
                            'bg-[#66BB6A]': item.source === 'graph',
                          }"></div>
                      </div>
                      <span class="w-[32px] text-right text-[#6B6B6B]">{{ item.weight.toFixed(2) }}</span>
                      <span v-if="item.trending" class="text-[#4CAF50]">↑</span>
                      <span v-if="item.is_new" class="text-[8px] text-[#FF5722] font-bold">NEW</span>
                    </div>
                  </div>
                </div>

                <!-- Legacy: Interest badges (for old tracking data) -->
                <div v-else-if="rd.initial_interests?.length || rd.drift_keywords?.length">
                  <span class="text-[8px] font-mono text-[#6B6B6B] uppercase block mb-1">Interests</span>
                  <div class="flex flex-wrap gap-1.5">
                    <template v-if="rd.initial_interests?.length">
                      <span v-for="int in rd.initial_interests" :key="'i-'+int"
                        class="text-[9px] font-mono px-2 py-0.5 bg-[#B5E8F0]/15 text-[#0097A7] border border-[#B5E8F0]/30">📌 {{ int }}</span>
                    </template>
                    <template v-if="rd.drift_keywords?.length">
                      <span v-for="kw in rd.drift_keywords" :key="'d-'+kw"
                        class="text-[9px] font-mono px-2 py-0.5 bg-[#FFE066]/20 text-[#FF8F00] border border-[#FFE066]/40">🔄 {{ kw }}</span>
                    </template>
                  </div>
                </div>

                <!-- Search Queries (multi-query) -->
                <div v-if="rd.search_queries?.length">
                  <span class="text-[8px] font-mono text-[#6B6B6B] uppercase block mb-0.5">ChromaDB Queries</span>
                  <div class="bg-[#B5E8F0]/5 p-1.5 border border-[#B5E8F0]/20 space-y-0.5">
                    <div v-for="(sq, si) in rd.search_queries" :key="si" class="flex items-center gap-1 text-[9px] font-mono">
                      <span class="text-[#6B6B6B]">q{{ si+1 }}</span>
                      <span class="text-[#999]">({{ sq.weight.toFixed(2) }})</span>
                      <span class="text-[#0097A7]">"{{ sq.query }}"</span>
                    </div>
                  </div>
                </div>

                <!-- Legacy: single search query -->
                <div v-else-if="rd.search_query">
                  <span class="text-[8px] font-mono text-[#6B6B6B] uppercase block mb-0.5">ChromaDB Search Query</span>
                  <pre class="text-[10px] text-[#0097A7] bg-[#B5E8F0]/10 p-2 whitespace-pre-wrap font-mono border border-[#B5E8F0]/30 max-h-[100px] overflow-y-auto">{{ rd.search_query }}</pre>
                </div>
                <div v-if="rd.graph_context && rd.graph_context !== '(no graph data)'">
                  <span class="text-[8px] font-mono text-[#6B6B6B] uppercase block mb-0.5">Graph Context</span>
                  <pre class="text-[10px] text-[#2D2D2D] bg-[#66BB6A]/5 p-2 whitespace-pre-wrap font-mono border border-[#66BB6A]/20">{{ rd.graph_context }}</pre>
                </div>
                <div v-if="rd.actions?.length">
                  <span class="text-[8px] font-mono text-[#6B6B6B] uppercase block mb-0.5">Actions Detail</span>
                  <div v-for="(a, ai) in rd.actions" :key="ai" class="text-[10px] text-[#2D2D2D] bg-white p-1.5 border border-[#E0DDD5] mb-1">
                    <span class="font-mono text-[#6B6B6B]">{{ a.type }}:</span> {{ a.text || '—' }}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- RIGHT SIDEBAR -->
      <aside class="w-[200px] border-l border-[#E0DDD5] bg-[#FBF8F3] flex flex-col p-6 gap-8 flex-shrink-0">
        <div class="flex flex-col gap-2">
          <span class="text-[10px] font-sans font-bold text-[#6B6B6B] uppercase tracking-widest">Active Agents</span>
          <span class="text-2xl font-mono text-[#66BB6A]">{{ profiles.length || numAgents || '—' }}</span>
        </div>
        <div class="flex flex-col gap-4">
          <span class="text-[10px] font-sans font-bold text-[#6B6B6B] uppercase tracking-widest">Aggregate</span>
          <div class="flex justify-between items-end border-b border-[#E0DDD5] pb-2">
            <span class="text-xs text-[#6B6B6B]">Actions</span>
            <span class="text-sm font-mono text-[#2D2D2D]">{{ progress.action_count || 0 }}</span>
          </div>
          <div class="flex justify-between items-end border-b border-[#E0DDD5] pb-2">
            <span class="text-xs text-[#6B6B6B]">Round</span>
            <span class="text-sm font-mono text-[#2D2D2D]">{{ progress.current_round || 0 }}</span>
          </div>
          <div v-if="estimatedMinutes" class="flex justify-between items-end border-b border-[#E0DDD5] pb-2">
            <span class="text-xs text-[#6B6B6B]">Est.</span>
            <span class="text-sm font-mono text-[#FFE066]">{{ estimatedMinutes }}m</span>
          </div>
        </div>
        <div class="flex flex-col gap-2 mt-auto">
          <span class="text-[10px] font-sans font-bold text-[#6B6B6B] uppercase tracking-widest">Status</span>
          <span :class="[
            'text-xl font-mono uppercase',
            simStatus === 'running' ? 'text-[#FFE066]' :
            simStatus === 'completed' ? 'text-[#66BB6A]' :
            simStatus === 'failed' ? 'text-[#FF8A80]' :
            simReady ? 'text-[#66BB6A]' : 'text-[#6B6B6B]'
          ]">{{ simStatus || (simReady ? 'READY' : 'IDLE') }}</span>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { simApi } from '../api/client'
import { useAppStore } from '../stores/appStore'

const store = useAppStore()

const tabs = ['Setup', 'Run', 'Monitor']
const activeTab = ref('Setup')
const error = ref('')
const prepareWarnings = ref([])

const stepLabels = [
  { id: '01', label: 'Upload' },
  { id: '02', label: 'Profiles' },
  { id: '03', label: 'Launch' },
]
const prepareStep = ref(store.campaignId ? 2 : 1)

// Setup
const numAgents = ref(10)
const numRounds = ref(24)
const preparing = ref(false)
const profiles = ref([])
const simReady = ref(false)

// Cognitive toggles
const cognitiveToggles = ref([
  { key: 'enable_agent_memory', label: 'Agent Memory', icon: 'psychology', enabled: true,
    desc: 'Lưu trữ & gợi lại ký ức agent qua FalkorDB giữa các round' },
  { key: 'enable_mbti_modifiers', label: 'MBTI Modifiers', icon: 'fingerprint', enabled: true,
    desc: 'Điều chỉnh hành vi dựa trên đặc điểm tính cách MBTI' },
  { key: 'enable_interest_drift', label: 'Interest Drift', icon: 'trending_up', enabled: true,
    desc: 'Theo dõi sự thay đổi sở thích agent qua từng round' },
  { key: 'enable_reflection', label: 'Reflection', icon: 'self_improvement', enabled: true,
    desc: 'Agent tự phản tư về hành vi trước đó (đang phát triển)' },
  { key: 'enable_graph_cognition', label: 'Knowledge Graph', icon: 'hub', enabled: false,
    desc: 'Inject tri thức từ KG vào context agent (tốn tài nguyên)' },
])

// Crisis Injection Setup
const crisisEnabled = ref(false)
const crisisEvents = ref([])

const scheduledCrises = computed(() => crisisEvents.value.filter(c => c.mode === 'scheduled'))
const realtimeCrises = computed(() => crisisEvents.value.filter(c => c.mode === 'realtime'))

function addCrisis() {
  crisisEvents.value.push({
    title: '',
    description: '',
    mode: 'scheduled',
    trigger_round: Math.max(1, Math.ceil(numRounds.value / 2)),
    severity: 0.5,
    _injected: false,
  })
}

function removeCrisis(index) {
  crisisEvents.value.splice(index, 1)
}

async function injectRealtimeCrisis(crisis) {
  if (!store.simId || crisis._injected) return
  try {
    await simApi.injectCrisis(store.simId, {
      title: crisis.title,
      description: crisis.description,
      severity: crisis.severity,
      crisis_type: 'custom',
      sentiment_shift: 'negative',
    })
    crisis._injected = true
  } catch (e) {
    error.value = e.response?.data?.detail || 'Crisis injection failed'
  }
}

// Monitor Tab
const monitorAgentId = ref('')
const monitorData = ref(null)
const monitorLoading = ref(false)
const monitorError = ref('')
const monitorExpanded = ref(new Set())

function toggleMonitorExpand(round) {
  const s = new Set(monitorExpanded.value)
  if (s.has(round)) s.delete(round)
  else s.add(round)
  monitorExpanded.value = s
}

async function loadMonitorData() {
  if (monitorAgentId.value === '') { monitorData.value = null; return }
  monitorLoading.value = true
  monitorError.value = ''
  
  // Find profile for selected agent
  const agentId = typeof monitorAgentId.value === 'string' ? parseInt(monitorAgentId.value) : monitorAgentId.value
  const prof = profiles.value.find(p => (p.agent_id ?? profiles.value.indexOf(p)) === agentId) || profiles.value[agentId]
  
  // Try cognitive API first (needs completed simulation with tracking)
  try {
    if (store.simId) {
      const res = await simApi.cognitive(store.simId)
      monitorData.value = res.data
      monitorLoading.value = false
      return
    }
  } catch {
    // Cognitive API not available — fall through to profile-based display
  }
  
  // Build from local profile data
  if (prof) {
    monitorData.value = {
      agent: {
        name: prof.realname || prof.name || `Agent ${agentId}`,
        id: agentId,
        mbti: prof.mbti || '—',
      },
      profile: {
        bio: prof.bio || '',
        persona: prof.user_char || prof.persona || '',
        profession: prof.profession || '',
        age: prof.age || '',
        gender: prof.gender || '',
        country: prof.country || '',
        interests: prof.interests || [],
        stance_label: prof.stance_label || '',
        entity_type: prof.entity_type || prof.role || '',
        influence_score: prof.influence_score,
        follower_count: prof.follower_count,
      },
      rounds: [],  // Empty — no simulation data yet
      total_rounds: 0,
      status: 'profile_only',
    }
  } else {
    monitorError.value = 'Không tìm thấy agent. Hãy Prepare Simulation trước.'
    monitorData.value = null
  }
  
  monitorLoading.value = false
}

// Expandable profile cards
const expandedProfiles = ref(new Set())
function toggleProfile(agentId) {
  const s = new Set(expandedProfiles.value)
  if (s.has(agentId)) s.delete(agentId)
  else s.add(agentId)
  expandedProfiles.value = s
}

// ── Cognitive Traits from MBTI (mirrors Python agent_cognition.py) ──
const _cogCache = {}
function getCogTraits(mbti) {
  if (!mbti) return { conviction: 0.6, forgetfulness: 0.15, curiosity: 0.30, impressionability: 0.15 }
  if (_cogCache[mbti]) return _cogCache[mbti]

  const defaults = { conviction: 0.6, forgetfulness: 0.15, curiosity: 0.30, impressionability: 0.15 }
  const mbtiMap = {
    J: { conviction: 0.80, curiosity: 0.20 },
    P: { conviction: 0.40, curiosity: 0.45 },
    S: { forgetfulness: 0.10 },
    N: { forgetfulness: 0.20 },
    F: { impressionability: 0.25 },
    T: { impressionability: 0.10 },
    E: { curiosity_bonus: 0.10 },
    I: { curiosity_bonus: -0.05 },
  }
  let curiosityBonus = 0
  for (const ch of mbti.toUpperCase()) {
    const mods = mbtiMap[ch] || {}
    for (const [k, v] of Object.entries(mods)) {
      if (k === 'curiosity_bonus') curiosityBonus = v
      else if (k in defaults) defaults[k] = v
    }
  }
  defaults.curiosity = Math.max(0.1, Math.min(0.5, defaults.curiosity + curiosityBonus))
  _cogCache[mbti] = defaults
  return defaults
}

// ── MBTI Avatar color class (Keirsey temperaments) ──
function getMbtiAvatarClass(mbti) {
  if (!mbti) return 'avatar-default'
  const m = mbti.toUpperCase()
  // Analyst: xNTx (INTJ, INTP, ENTJ, ENTP)
  if (m.includes('N') && m.includes('T')) return 'avatar-analyst'
  // Diplomat: xNFx (INFJ, INFP, ENFJ, ENFP)
  if (m.includes('N') && m.includes('F')) return 'avatar-diplomat'
  // Sentinel: xSxJ (ISTJ, ISFJ, ESTJ, ESFJ)
  if (m.includes('S') && m.includes('J')) return 'avatar-sentinel'
  // Explorer: xSxP (ISTP, ISFP, ESTP, ESFP)
  if (m.includes('S') && m.includes('P')) return 'avatar-explorer'
  return 'avatar-default'
}

// ── Extract initial interests from profile ──
const _STOP_WORDS = new Set([
  'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
  'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'shall',
  'should', 'may', 'might', 'must', 'can', 'could', 'this', 'that',
  'these', 'those', 'with', 'from', 'into', 'about', 'their', 'your',
  'which', 'what', 'when', 'where', 'while', 'there', 'then', 'than',
  'they', 'them', 'other', 'more', 'also', 'very', 'just', 'often',
  'such', 'many', 'most', 'some', 'each', 'every', 'both', 'well',
  'much', 'same', 'different', 'through', 'during', 'before', 'after',
  'between', 'under', 'over', 'like', 'make', 'made', 'know', 'take',
  'come', 'find', 'give', 'tell', 'work', 'call', 'keep', 'help',
  'think', 'feel', 'want', 'need', 'look', 'turn', 'start', 'show',
  'name', 'agent', 'người', 'không', 'được', 'trong', 'những', 'nhưng',
])

function getInitialInterests(profile) {
  // 1. Explicit interests field
  let interests = profile.interests || []
  if (typeof interests === 'string' && interests) {
    interests = interests.split(',').map(s => s.trim()).filter(Boolean)
  }
  if (interests.length > 0) return interests.slice(0, 5)

  // 2. Extract keywords from persona
  const persona = profile.user_char || profile.persona || ''
  if (!persona || persona.length < 20) return []

  const words = persona.toLowerCase()
    .replace(/[.,!?"'()\[\]{}#@]/g, ' ')
    .split(/\s+/)
    .filter(w => w.length > 4 && !_STOP_WORDS.has(w) && /^[a-zA-ZÀ-ÿ]+$/.test(w))

  const freq = {}
  for (const w of words) freq[w] = (freq[w] || 0) + 1
  return Object.entries(freq)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([word]) => word)
}

// Run
const simStatus = ref('')
const progress = ref({})
const actions = ref([])
const liveEvents = ref([])
let pollTimer = null

const progressPct = computed(() => {
  if (!progress.value.total_rounds) return 0
  return (progress.value.current_round / progress.value.total_rounds) * 100
})

// ── Run Tab: Agent Name Resolution ──
const agentNameMap = computed(() => {
  const map = {}
  for (const p of profiles.value) {
    const id = p.agent_id ?? p.user_id
    if (id != null) map[id] = p.realname || p.name || p.username || `Agent ${id}`
  }
  return map
})

// ── Run Tab: Filtered Actions (remove trace/sign_up/refresh noise) ──
const filteredActions = computed(() => {
  return actions.value.filter(a => {
    const t = (a.action_type || '').toLowerCase()
    return t !== 'trace' && t !== 'sign_up' && t !== 'do_nothing' && t !== 'refresh'
  })
})

// ── Run Tab: Action Stats ──
const actionStats = computed(() => {
  const fa = filteredActions.value
  const agentIds = new Set()
  let posts = 0, comments = 0, likes = 0
  for (const a of fa) {
    const t = (a.action_type || '').toLowerCase()
    if (t === 'create_post') posts++
    else if (t === 'create_comment') comments++
    else if (t === 'like_post') likes++
    if (a.agent_id != null) agentIds.add(a.agent_id)
    else if (a.user_id != null) agentIds.add(a.user_id)
  }
  return { posts, comments, likes, uniqueAgents: agentIds.size }
})

// ── Run Tab: Posts with nested comments + like counts ──
const postActions = computed(() => {
  const fa = filteredActions.value
  
  // Collect posts
  const posts = fa.filter(a => (a.action_type || '').toLowerCase() === 'create_post')
    .map(p => ({ ...p, comments: [], num_comments: 0, num_likes: 0 }))
  
  // Build post_id lookup map
  const postMap = {}
  posts.forEach((p, idx) => {
    const pid = p.post_id ?? (idx + 1)
    postMap[pid] = p
  })
  
  // Attach comments to their parent posts
  const comments = fa.filter(a => (a.action_type || '').toLowerCase() === 'create_comment')
  for (const c of comments) {
    // Try to find parent post by post_id in info
    const info = c.info || {}
    const parentId = info.post_id ?? c.post_id
    if (parentId == null) continue  // skip if no post_id
    const parent = postMap[parentId]
    if (!parent) continue  // skip if post not found
    if (parent) {
      parent.comments.push({
        agent_name: c.agent_name || `Agent ${c.user_id}`,
        agent_id: c.agent_id ?? c.user_id,
        content: c.content || '',
        timestamp: c.timestamp,
      })
      parent.num_comments = parent.comments.length
    }
  }
  
  // Count likes per post
  const likes = fa.filter(a => (a.action_type || '').toLowerCase() === 'like_post')
  for (const l of likes) {
    const info = l.info || {}
    const parentId = info.post_id ?? l.post_id
    if (parentId == null) continue
    const parent = postMap[parentId]
    if (!parent) continue
    if (parent) {
      parent.num_likes = (parent.num_likes || 0) + 1
    }
  }
  
  return posts
})

// ── Run Tab: Comment expansion state ──
const expandedComments = ref(new Set())
function toggleComments(postId) {
  const s = new Set(expandedComments.value)
  if (s.has(postId)) s.delete(postId)
  else s.add(postId)
  expandedComments.value = s
}

function getAgentName(entry) {
  // Prefer backend-enriched agent_name
  if (entry.agent_name && !entry.agent_name.startsWith('Agent ')) return entry.agent_name
  if (entry.agent_name) return entry.agent_name
  const id = entry.agent_id ?? entry.user_id
  if (agentNameMap.value[id]) return agentNameMap.value[id]
  // Try to extract from entry.info (trace/sign_up events)
  if (entry.info) {
    try {
      const info = typeof entry.info === 'string' ? JSON.parse(entry.info) : entry.info
      if (info.name) return info.name
    } catch { /* ignore */ }
  }
  return id != null ? `Agent ${id}` : 'Unknown'
}

function getAgentInitial(entry) {
  const name = getAgentName(entry)
  // Return first letter of the name
  if (name.startsWith('Agent ')) return name.replace('Agent ', '')[0] || '?'
  return name.charAt(0).toUpperCase()
}

function getActionColor(actionType) {
  const t = (actionType || '').toLowerCase()
  const colors = {
    'create_post':    { bg: 'bg-[#B5E8F0]/20 text-[#B5E8F0]', badge: 'bg-[#B5E8F0]/10 text-[#B5E8F0] border border-[#B5E8F0]/20' },
    'create_comment': { bg: 'bg-[#D5C4F7]/20 text-[#D5C4F7]', badge: 'bg-[#D5C4F7]/10 text-[#D5C4F7] border border-[#D5C4F7]/20' },
    'like_post':      { bg: 'bg-[#E85D75]/20 text-[#E85D75]', badge: 'bg-[#E85D75]/10 text-[#E85D75] border border-[#E85D75]/20' },
    'follow':         { bg: 'bg-[#66BB6A]/20 text-[#66BB6A]', badge: 'bg-[#66BB6A]/10 text-[#66BB6A] border border-[#66BB6A]/20' },
    'repost':         { bg: 'bg-[#FFE066]/20 text-[#FFE066]', badge: 'bg-[#FFE066]/10 text-[#FFE066] border border-[#FFE066]/20' },
  }
  return colors[t] || { bg: 'bg-[#E0DDD5] text-[#6B6B6B]', badge: 'bg-[#E0DDD5] text-[#6B6B6B]' }
}

function getActionIcon(actionType) {
  const t = (actionType || '').toLowerCase()
  const icons = {
    'create_post': '📝',
    'create_comment': '💬',
    'like_post': '❤️',
    'follow': '👤',
    'repost': '🔄',
  }
  return icons[t] || '📌'
}

function getActionLabel(actionType) {
  const t = (actionType || '').toLowerCase()
  const labels = {
    'create_post': 'Bài viết',
    'create_comment': 'Bình luận',
    'like_post': 'Thích',
    'follow': 'Theo dõi',
    'repost': 'Chia sẻ',
  }
  return labels[t] || actionType
}

function formatTimestamp(ts) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return String(ts).substring(0, 16)
    return d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return String(ts).substring(0, 16)
  }
}


async function prepareSimulation() {
  preparing.value = true
  error.value = ''
  prepareWarnings.value = []
  prepareStep.value = 2
  try {
    // Build cognitive toggles object
    const toggles = {}
    for (const t of cognitiveToggles.value) {
      toggles[t.key] = t.enabled
    }

    // Build crisis events for backend (scheduled ones go in config, realtime injected at runtime)
    const crisisPayload = crisisEnabled.value
      ? crisisEvents.value
          .filter(c => c.title.trim())  // only send crises with a title
          .map(c => ({
            trigger_round: c.mode === 'scheduled' ? c.trigger_round : 1,
            crisis_type: 'custom',
            title: c.title,
            description: c.description,
            severity: c.severity,
            sentiment_shift: 'negative',
          }))
      : []

    const res = await simApi.prepare(store.campaignId, numAgents.value, numRounds.value, store.groupId, toggles, crisisPayload)
    store.setSimId(res.data.sim_id)

    // Load profiles from separate endpoint
    try {
      const profRes = await simApi.profiles(res.data.sim_id)
      profiles.value = profRes.data.profiles || []
    } catch { profiles.value = [] }

    prepareStep.value = 3
    simReady.value = true

    // Persist to store
    store.setSimPrepData({
      profiles: profiles.value,
      simReady: true,
      numAgents: numAgents.value,
      numRounds: numRounds.value,
      prepareStep: 3,
    })
  } catch (e) {
    error.value = e.response?.data?.detail || e.response?.data?.error || 'Prepare failed'
  } finally {
    preparing.value = false
  }
}

async function startSimulation() {
  error.value = ''
  liveEvents.value = []
  actions.value = []
  try {
    await simApi.start(store.simId, store.groupId)
    activeTab.value = 'Run'
    startSSE()
  } catch (e) {
    error.value = e.response?.data?.detail || e.response?.data?.error || 'Start failed'
  }
}

// ── SSE Streaming + Polling fallback ──
let lastFetchedRound = -1
let eventSource = null

function normalizeAction(a, idx) {
  const info = typeof a.info === 'string' ? (() => { try { return JSON.parse(a.info) } catch { return {} } })() : (a.info || {})
  return {
    ...a,
    post_id: a.post_id || info.post_id || idx,
    content: a.content || info.content || info.text || '',
    num_likes: a.num_likes ?? info.num_likes ?? 0,
    num_comments: a.num_comments ?? info.num_comments ?? 0,
    num_dislikes: a.num_dislikes ?? info.num_dislikes ?? 0,
    agent_name: a.agent_name || agentNameMap.value[a.user_id] || `Agent ${a.user_id}`,
    agent_id: a.agent_id ?? a.user_id,
  }
}

function startSSE() {
  if (!store.simId) return
  stopSSE()

  const url = `/api/sim/${store.simId}/stream`
  eventSource = new EventSource(url)

  eventSource.addEventListener('progress', (e) => {
    try {
      const data = JSON.parse(e.data)
      progress.value = data
      simStatus.value = data.status || 'running'
    } catch { /* ignore */ }
  })

  eventSource.addEventListener('actions', (e) => {
    try {
      const data = JSON.parse(e.data)
      const newActions = (data.new_actions || []).map(
        (a, idx) => normalizeAction(a, actions.value.length + idx)
      )
      // Append new actions to existing
      if (newActions.length > 0) {
        actions.value = [...actions.value, ...newActions]
      }
    } catch { /* ignore */ }
  })

  eventSource.addEventListener('log', (e) => {
    try {
      const data = JSON.parse(e.data)
      const lines = data.lines || []
      // Add to live events for the Live Stream display
      const now = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      for (const line of lines) {
        // Parse log lines into events
        if (line.includes('[POST]')) {
          liveEvents.value.unshift({ event: 'post', timestamp: now, message: line })
        } else if (line.includes('[COMMENT]')) {
          liveEvents.value.unshift({ event: 'comment', timestamp: now, message: line })
        } else if (line.includes('[LIKE]')) {
          liveEvents.value.unshift({ event: 'like', timestamp: now, message: line })
        } else if (line.includes('ROUND')) {
          const match = line.match(/ROUND\s+(\d+)\/(\d+)/)
          if (match) {
            liveEvents.value.unshift({
              event: 'round_start',
              timestamp: now,
              round: parseInt(match[1]),
              total_rounds: parseInt(match[2]),
            })
          }
        } else if (line.includes('summary:')) {
          liveEvents.value.unshift({ event: 'round_actions', timestamp: now, message: line })
        }
      }
      // Keep only last 50 events
      if (liveEvents.value.length > 50) liveEvents.value = liveEvents.value.slice(0, 50)
    } catch { /* ignore */ }
  })

  eventSource.addEventListener('done', (e) => {
    try {
      const data = JSON.parse(e.data)
      simStatus.value = data.status || 'completed'
      progress.value = { ...progress.value, status: data.status }
      store.completeStep('simulation')
      // Fetch final actions one more time
      fetchAllActions()
    } catch { /* ignore */ }
    stopSSE()
  })

  eventSource.onerror = () => {
    console.warn('SSE connection failed, falling back to polling')
    stopSSE()
    startPolling()
  }
}

function stopSSE() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

async function fetchAllActions() {
  if (!store.simId) return
  try {
    const actionsRes = await simApi.actions(store.simId).catch(() => ({ data: { actions: [] } }))
    const rawActions = actionsRes.data.actions || []
    actions.value = rawActions.map((a, idx) => normalizeAction(a, idx))
  } catch { /* ignore */ }
}

async function pollProgress() {
  if (!store.simId) return
  try {
    const statusRes = await simApi.progress(store.simId).catch(() => ({ data: {} }))
    progress.value = statusRes.data || {}
    simStatus.value = statusRes.data.status || ''

    const currentRound = statusRes.data.current_round ?? 0
    if (currentRound !== lastFetchedRound || simStatus.value === 'completed' || simStatus.value === 'failed') {
      lastFetchedRound = currentRound
      await fetchAllActions()
    }

    if (simStatus.value === 'completed' || simStatus.value === 'failed') {
      stopPolling()
    }
  } catch { /* ignore polling errors */ }
}

function startPolling() {
  lastFetchedRound = -1
  pollProgress()
  pollTimer = setInterval(pollProgress, 10000)
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

function stopAll() {
  stopSSE()
  stopPolling()
}

onMounted(() => {
  // Restore simulation prep state from store (survives route changes)
  const saved = store.simPrepData
  if (saved && saved.simReady) {
    profiles.value = saved.profiles || []
    simReady.value = true
    numAgents.value = saved.numAgents || 10
    numRounds.value = saved.numRounds || 24
    prepareStep.value = saved.prepareStep || 3
  }

  if (store.simId) {
    activeTab.value = 'Run'
    startSSE()
  }
})

onUnmounted(() => {
  stopAll()
})

const estimatedMinutes = computed(() => {
  if (!progress.value.total_rounds || !progress.value.current_round) return ''
  const elapsed = progress.value.elapsed_seconds || 0
  if (elapsed < 5 || progress.value.current_round < 1) return ''
  const perRound = elapsed / progress.value.current_round
  const remaining = (progress.value.total_rounds - progress.value.current_round) * perRound
  return Math.ceil(remaining / 60)
})
</script>

<style scoped>
/* ===== MEMPHIS SIMULATION OVERRIDES ===== */

/* Root container */
.flex-1.flex.flex-col.overflow-hidden {
  font-family: 'DM Sans', system-ui, sans-serif;
  position: relative;
}

/* Floating geometric decoration on root */
.flex-1.flex.flex-col.overflow-hidden::before {
  content: '';
  position: fixed;
  top: 15%;
  right: 12%;
  width: 140px;
  height: 140px;
  border: 4px solid #9B59B6;
  border-radius: 50%;
  opacity: 0.05;
  pointer-events: none;
  animation: simFloat 8s ease-in-out infinite;
  z-index: 0;
}

.flex-1.flex.flex-col.overflow-hidden::after {
  content: '';
  position: fixed;
  bottom: 20%;
  left: 8%;
  width: 0;
  height: 0;
  border-left: 50px solid transparent;
  border-right: 50px solid transparent;
  border-bottom: 86px solid #FFE066;
  opacity: 0.04;
  pointer-events: none;
  animation: simFloat 10s ease-in-out infinite reverse;
  z-index: 0;
}

@keyframes simFloat {
  0%, 100% { transform: translate(0, 0) rotate(0deg); }
  25% { transform: translate(10px, -15px) rotate(5deg); }
  50% { transform: translate(-5px, 10px) rotate(-3deg); }
  75% { transform: translate(8px, 5px) rotate(2deg); }
}

/* Header — zigzag bottom */
header {
  border-bottom: 3px solid #D5C4F7 !important;
  position: relative;
  z-index: 2;
}

header::after {
  content: '';
  position: absolute;
  bottom: -11px;
  left: 0;
  right: 0;
  height: 8px;
  background: linear-gradient(135deg, #F5F0E8 33.33%, transparent 33.33%) 0 0,
              linear-gradient(225deg, #F5F0E8 33.33%, transparent 33.33%) 0 0;
  background-size: 12px 8px;
  background-repeat: repeat-x;
  z-index: 2;
}

/* Tab bar — thick active underline */
.px-8.border-b {
  border-bottom: 2px solid #E0DDD5 !important;
}

/* Tab buttons — Memphis style */
.px-8.border-b button {
  font-family: 'Space Mono', sans-serif !important;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  font-size: 11px;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* Section titles */
h2 {
  font-family: 'Space Mono', sans-serif !important;
  font-weight: 700 !important;
  letter-spacing: -0.01em;
}

h3 {
  font-family: 'Space Mono', sans-serif !important;
}

/* Labels — mono uppercase */
label {
  font-family: 'JetBrains Mono', monospace !important;
}

/* Inputs — square Memphis */
input[type="number"], input[type="text"] {
  border: 2px solid #E0DDD5 !important;
  border-radius: 0 !important;
  font-family: 'JetBrains Mono', monospace !important;
  transition: all 0.2s;
}

input[type="number"]:focus, input[type="text"]:focus {
  border-color: #66BB6A !important;
  box-shadow: 3px 3px 0 #66BB6A !important;
  outline: none;
}

/* Buttons — Memphis offset shadow */
button[class*="bg-[#66BB6A]"] {
  border-radius: 0 !important;
  border: 2px solid #F5F0E8 !important;
  box-shadow: 4px 4px 0 #9B59B6;
  font-family: 'Space Mono', sans-serif !important;
  font-weight: 700;
  letter-spacing: 0.05em;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

button[class*="bg-[#66BB6A]"]:hover {
  transform: translate(-2px, -2px);
  box-shadow: 6px 6px 0 #9B59B6;
}

button[class*="bg-[#66BB6A]"]:active {
  transform: translate(2px, 2px);
  box-shadow: 0 0 0 transparent;
}

/* Step badges — square Memphis */
span[class*="bg-[#66BB6A]/10"] {
  border-radius: 0 !important;
  border: 2px solid rgba(107, 203, 119, 0.3) !important;
  box-shadow: 2px 2px 0 rgba(107, 203, 119, 0.2);
  font-family: 'Space Mono', sans-serif !important;
  font-weight: 700;
}

/* Agent profile cards — Memphis card */
div[class*="bg-[#FFFFFF]"][class*="border"] {
  border-radius: 0 !important;
  border-width: 2px !important;
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

div[class*="bg-[#FFFFFF]"][class*="border"]:hover {
  box-shadow: 3px 3px 0 rgba(132, 94, 194, 0.3);
  transform: translateY(-1px);
}

/* Agent ID squares */
div[class*="w-8"][class*="h-8"][class*="bg-[#E0DDD5]"] {
  border-radius: 0 !important;
  border: 2px solid #D5C4F7;
  box-shadow: 2px 2px 0 rgba(132, 94, 194, 0.3);
}

/* Status dots — square Memphis */
span[class*="rounded-full"][class*="w-2"] {
  border-radius: 0 !important;
}

span[class*="rounded-full"][class*="w-2.5"] {
  border-radius: 0 !important;
}

/* Progress bar — square track */
div[class*="rounded-full"][class*="bg-[#E0DDD5]"] {
  border-radius: 0 !important;
  border: 1px solid #E0DDD5;
  height: 8px !important;
}

div[class*="rounded-full"][class*="bg-[#E0DDD5]"] > div {
  border-radius: 0 !important;
}

/* Post cards — Memphis styling */
div[class*="rounded-lg"][class*="bg-[#FFFFFF]"] {
  border-radius: 0 !important;
  border: 2px solid #E0DDD5 !important;
  box-shadow: 3px 3px 0 rgba(45, 43, 85, 0.3);
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

div[class*="rounded-lg"][class*="bg-[#FFFFFF]"]:hover {
  box-shadow: 5px 5px 0 #D5C4F7;
  transform: translate(-1px, -1px);
}

/* Post avatar circles — square Memphis */
div[class*="rounded-full"][class*="bg-gradient-to-br"] {
  border-radius: 0 !important;
  border: 2px solid #F5F0E8;
  box-shadow: 2px 2px 0 #9B59B6;
}

/* Comment avatars */
div[class*="rounded-full"][class*="bg-[#E0DDD5]"][class*="w-6"] {
  border-radius: 0 !important;
  border: 1px solid #D5C4F7;
}

/* Action badges — square */
span[class*="py-0.5"][class*="text-[9px]"] {
  border-radius: 0 !important;
}

/* Quick stats cards — Memphis offset */
.grid.grid-cols-5 > div {
  border: 2px solid #E0DDD5 !important;
  border-radius: 0 !important;
  box-shadow: 3px 3px 0 rgba(45, 43, 85, 0.3);
  transition: all 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.grid.grid-cols-5 > div:hover {
  box-shadow: 4px 4px 0 #D5C4F7;
  transform: translate(-1px, -1px);
}

.grid.grid-cols-5 > div span:last-child {
  font-family: 'Space Mono', sans-serif !important;
  font-weight: 700;
}

/* Right sidebar — polka dots + pink border */
aside[class*="w-[200px]"] {
  border-left: 3px solid #9B59B6 !important;
  position: relative;
}

aside[class*="w-[200px]"]::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: radial-gradient(circle, #D5C4F7 1px, transparent 1px);
  background-size: 20px 20px;
  opacity: 0.05;
  pointer-events: none;
}

aside[class*="w-[200px]"] span[class*="text-2xl"] {
  font-family: 'Space Mono', sans-serif !important;
  font-weight: 700;
}

/* Live stream event log */
div[class*="bg-[#F5F0E8]"][class*="max-h-48"] {
  border: 2px solid #E0DDD5 !important;
  border-radius: 0 !important;
}

/* Stepper step numbers */
div[class*="w-4"][class*="h-4"][class*="rounded-full"] {
  border-radius: 0 !important;
}

/* Empty state icon */
div[class*="w-16"][class*="h-16"][class*="rounded-full"] {
  border-radius: 0 !important;
  border: 3px solid #FFE066;
  box-shadow: 4px 4px 0 #9B59B6;
}

/* Error bars — Memphis style */
div[class*="border-l-2"][class*="border-[#FF8A80]"] {
  border-left-width: 4px !important;
  border: 2px solid #FF8A80 !important;
  border-left-width: 4px !important;
  border-radius: 0 !important;
  box-shadow: 3px 3px 0 rgba(255, 107, 107, 0.2);
}

div[class*="border-l-2"][class*="border-[#FFE066]"] {
  border-left-width: 4px !important;
  border: 2px solid #FFE066 !important;
  border-left-width: 4px !important;
  border-radius: 0 !important;
  box-shadow: 3px 3px 0 rgba(255, 217, 61, 0.2);
}
</style>
