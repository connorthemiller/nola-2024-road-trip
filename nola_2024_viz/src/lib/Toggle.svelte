<script>
	export let lines
	let open = false
	const toggle = () => open = !open
</script>

<div class="toggle" class:open class:lines on:click={toggle}>
	<!-- if it's a "lines" style  -->
	{#if lines}
	{open ? '' : '↕️'}
	{:else}
	{open ? '[-]' : '[+]'}
	{/if}
</div>
<div style:display={open ? 'block' : 'none'}>
	<slot />
</div>

<style>
	.toggle{
		cursor: pointer;
	}
	.toggle.lines {
		width: 6px;
		background: #eee;
		height: 100%;
		border-radius: 20px;
		display: block;
		position: absolute;
		left: 0;
		top: 0;
	}
	.toggle.lines:hover {
		background: #ddd;
	}
</style>